#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import os
import re
import wave
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from common import (
    ensure_dir,
    find_executable,
    read_json,
    run_cmd,
    structured_error,
    summarize_cmd,
    utc_now_iso,
    write_json,
)

_OCR_ENGINE: Optional[Any] = None
_WHISPER_MODELS: Dict[str, Any] = {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="抽取可用于拆解的信号：帧、OCR、字幕、转写")
    parser.add_argument("--fetch-result", required=True, help="fetch_content.py 输出的 JSON")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--result-file", help="输出 JSON，默认 output-dir/signals.json")
    parser.add_argument("--whisper-model", default=os.getenv("VCB_WHISPER_MODEL", "small"))
    return parser.parse_args()


def _read_text_file(path: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return ""


def _strip_sub_line(line: str) -> str:
    line = re.sub(r"<[^>]+>", "", line)
    line = re.sub(r"\{[^}]+\}", "", line)
    return line.strip()


def _parse_subtitle_file(path: Path) -> List[Dict[str, Any]]:
    raw = _read_text_file(path)
    chunks: List[Dict[str, Any]] = []
    if not raw.strip():
        return chunks

    for idx, line in enumerate(raw.splitlines(), start=1):
        text = _strip_sub_line(line)
        if not text:
            continue
        if re.match(r"^\d+$", text):
            continue
        if "-->" in text:
            continue
        chunks.append(
            {
                "start": None,
                "end": None,
                "text": text,
                "source": str(path),
                "line": idx,
            }
        )
    return chunks


def _ffmpeg_extract_frames(video_path: Path, frame_dir: Path) -> Tuple[List[str], List[Dict[str, Any]]]:
    logs: List[Dict[str, Any]] = []
    frames: List[str] = []
    ffmpeg = find_executable("ffmpeg")
    if not ffmpeg:
        return frames, [{"step": "ffmpeg", "warning": "ffmpeg 未安装，切换到 av 抽帧"}]

    first_frame = frame_dir / "frame_000_first.jpg"
    cmd_first = [ffmpeg, "-y", "-i", str(video_path), "-ss", "0", "-frames:v", "1", str(first_frame)]
    res1 = run_cmd(cmd_first)
    logs.append({"step": "first_frame", **summarize_cmd(res1)})
    if first_frame.exists():
        frames.append(str(first_frame))

    scene_pattern = frame_dir / "frame_scene_%03d.jpg"
    cmd_scene = [
        ffmpeg,
        "-y",
        "-i",
        str(video_path),
        "-vf",
        "select=gt(scene\\,0.35)",
        "-vsync",
        "vfr",
        "-frames:v",
        "8",
        str(scene_pattern),
    ]
    res2 = run_cmd(cmd_scene)
    logs.append({"step": "scene_frames", **summarize_cmd(res2)})

    for p in sorted(frame_dir.glob("frame_scene_*.jpg")):
        frames.append(str(p))
    return frames, logs


def _av_extract_frames(video_path: Path, frame_dir: Path, max_frames: int = 9) -> Tuple[List[str], List[Dict[str, Any]]]:
    logs: List[Dict[str, Any]] = []
    frames: List[str] = []
    try:
        import av  # type: ignore
    except Exception as exc:
        return frames, [{"step": "av_frames", "error": f"av 不可用: {exc}"}]

    try:
        container = av.open(str(video_path))
        stream = container.streams.video[0]
        fps = float(stream.average_rate) if stream.average_rate else 25.0
        interval = max(1, int(fps * 3))

        frame_idx = 0
        saved = 0
        for frame in container.decode(video=0):
            should_save = frame_idx == 0 or (frame_idx % interval == 0)
            if should_save:
                out = frame_dir / f"frame_av_{saved:03d}.jpg"
                frame.to_image().save(out, format="JPEG")
                frames.append(str(out))
                saved += 1
                if saved >= max_frames:
                    break
            frame_idx += 1

        container.close()
        logs.append({"step": "av_frames", "saved": len(frames), "interval": interval})
    except Exception as exc:
        logs.append({"step": "av_frames", "error": str(exc)})

    return frames, logs


def _extract_frames(video_path: Path, frame_dir: Path) -> Tuple[List[str], List[Dict[str, Any]]]:
    frames, logs = _ffmpeg_extract_frames(video_path, frame_dir)
    if frames:
        return frames, logs
    av_frames, av_logs = _av_extract_frames(video_path, frame_dir)
    return av_frames, logs + av_logs


def _ffmpeg_extract_audio(video_path: Path, audio_path: Path) -> Dict[str, Any]:
    ffmpeg = find_executable("ffmpeg")
    if not ffmpeg:
        return {"step": "audio", "warning": "ffmpeg 未安装，切换到 av 抽音频"}
    cmd = [ffmpeg, "-y", "-i", str(video_path), "-vn", "-ac", "1", "-ar", "16000", str(audio_path)]
    res = run_cmd(cmd)
    return {"step": "audio", **summarize_cmd(res)}


def _av_extract_audio(video_path: Path, audio_path: Path) -> Dict[str, Any]:
    try:
        import av  # type: ignore
        import numpy as np  # type: ignore
    except Exception as exc:
        return {"step": "av_audio", "error": f"依赖不可用: {exc}"}

    try:
        container = av.open(str(video_path))
        if not container.streams.audio:
            container.close()
            return {"step": "av_audio", "warning": "视频无音轨"}

        stream = container.streams.audio[0]
        resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=16000)

        with wave.open(str(audio_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            total = 0
            for frame in container.decode(stream):
                out = resampler.resample(frame)
                frames = out if isinstance(out, list) else [out]
                for afr in frames:
                    arr = afr.to_ndarray()
                    if arr.size == 0:
                        continue
                    pcm = arr.astype(np.int16, copy=False).tobytes()
                    wf.writeframes(pcm)
                    total += arr.shape[-1]

        container.close()
        if audio_path.exists() and audio_path.stat().st_size > 44:
            return {"step": "av_audio", "written": str(audio_path), "samples": total}
        return {"step": "av_audio", "warning": "未写入有效音频"}
    except Exception as exc:
        return {"step": "av_audio", "error": str(exc)}


def _extract_audio(video_path: Path, audio_path: Path) -> Dict[str, Any]:
    log = _ffmpeg_extract_audio(video_path, audio_path)
    if audio_path.exists() and audio_path.stat().st_size > 44:
        return log
    log2 = _av_extract_audio(video_path, audio_path)
    if isinstance(log, dict):
        return {"ffmpeg": log, "av": log2}
    return log2


def _video_resolution(video_path: Path) -> Tuple[Optional[int], Optional[int]]:
    try:
        import av  # type: ignore

        container = av.open(str(video_path))
        stream = container.streams.video[0]
        width = int(stream.width or 0) or None
        height = int(stream.height or 0) or None
        container.close()
        if width and height:
            return width, height
    except Exception:
        pass

    ffprobe = find_executable("ffprobe")
    if not ffprobe:
        return None, None
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "csv=s=x:p=0",
        str(video_path),
    ]
    res = run_cmd(cmd)
    if res.code != 0:
        return None, None
    raw = res.stdout.strip()
    if "x" not in raw:
        return None, None
    try:
        w, h = raw.split("x", 1)
        return int(w), int(h)
    except Exception:
        return None, None


def _aspect_ratio_label(width: Optional[int], height: Optional[int]) -> str:
    if not width or not height or width <= 0 or height <= 0:
        return "unknown"
    g = math.gcd(width, height)
    a = width // g
    b = height // g
    if a == 9 and b == 16:
        return "9:16"
    if a == 16 and b == 9:
        return "16:9"
    if a == 1 and b == 1:
        return "1:1"
    return f"{a}:{b}"


def _infer_subtitle_style(
    transcript_chunks: List[Dict[str, Any]], ocr_hits: List[Dict[str, Any]]
) -> Dict[str, Any]:
    text_density = 0
    if transcript_chunks:
        text_density = int(sum(len(x.get("text", "")) for x in transcript_chunks[:10]) / max(len(transcript_chunks[:10]), 1))

    size = "unknown"
    font_style = "unknown"
    conf = 0.2
    reason = "未检测到足够的画面文字几何信息，仅可做弱推断。"

    if ocr_hits and transcript_chunks:
        size = "中号（推断）"
        font_style = "无衬线加粗（推断）"
        conf = 0.38
        reason = "画面 OCR 与口播文本都存在，常见于移动端口播字幕模板。"
    elif ocr_hits:
        size = "中号（低置信推断）"
        font_style = "无衬线（低置信推断）"
        conf = 0.3
        reason = "存在可读画面文字，但缺少字幕框几何信息。"
    elif transcript_chunks:
        size = "中小号（低置信推断）"
        font_style = "无衬线（低置信推断）"
        conf = 0.26
        reason = "有口播文本但 OCR 缺失，按常见短视频字幕样式给出低置信推断。"

    if text_density > 25 and conf > 0.25:
        size = "中小号（推断）"
        conf = min(0.45, conf + 0.05)

    return {
        "subtitle_size": size,
        "font_style": font_style,
        "confidence": round(conf, 2),
        "reason": reason,
    }


def _get_rapidocr_engine() -> Optional[Any]:
    global _OCR_ENGINE
    if _OCR_ENGINE is not None:
        return _OCR_ENGINE
    try:
        from rapidocr_onnxruntime import RapidOCR  # type: ignore

        _OCR_ENGINE = RapidOCR()
        return _OCR_ENGINE
    except Exception:
        return None


def _ocr_image(path: Path) -> Tuple[str, float]:
    engine = _get_rapidocr_engine()
    if engine is not None:
        try:
            result, _ = engine(str(path))
            if result:
                texts: List[str] = []
                scores: List[float] = []
                for line in result:
                    if len(line) >= 3:
                        txt = str(line[1]).strip()
                        conf = float(line[2])
                    elif len(line) >= 2:
                        txt = str(line[1]).strip()
                        conf = 0.6
                    else:
                        txt = ""
                        conf = 0.0
                    if txt:
                        texts.append(txt)
                        scores.append(conf)
                if texts:
                    text = "\n".join(texts)
                    avg_conf = sum(scores) / max(len(scores), 1)
                    return text, round(float(avg_conf), 2)
        except Exception:
            pass

    tesseract = find_executable("tesseract")
    if not tesseract:
        return "", 0.0
    cmd = [tesseract, str(path), "stdout", "-l", "chi_sim+eng"]
    res = run_cmd(cmd)
    if res.code != 0:
        return "", 0.0
    text = res.stdout.strip()
    if not text:
        return "", 0.0
    alpha_num = sum(1 for ch in text if ch.isalnum())
    conf = min(0.95, max(0.25, alpha_num / max(len(text), 1)))
    return text, round(conf, 2)


def _asr_with_openai(audio_path: Path) -> Tuple[List[Dict[str, Any]], List[str]]:
    logs: List[str] = []
    chunks: List[Dict[str, Any]] = []
    if not audio_path.exists():
        return chunks, logs

    try:
        from openai import OpenAI  # type: ignore
    except Exception:
        logs.append("openai SDK 不可用，跳过 OpenAI ASR")
        return chunks, logs

    if not os.getenv("OPENAI_API_KEY"):
        logs.append("未设置 OPENAI_API_KEY，跳过 OpenAI ASR")
        return chunks, logs

    try:
        client = OpenAI()
        with audio_path.open("rb") as f:
            resp = client.audio.transcriptions.create(model="gpt-4o-mini-transcribe", file=f)
        text = getattr(resp, "text", "") or ""
        if text.strip():
            for i, sentence in enumerate(re.split(r"(?<=[。！？!?])", text), start=1):
                sentence = sentence.strip()
                if not sentence:
                    continue
                chunks.append(
                    {
                        "start": None,
                        "end": None,
                        "text": sentence,
                        "source": str(audio_path),
                        "line": i,
                    }
                )
            logs.append("OpenAI ASR 完成")
        else:
            logs.append("OpenAI ASR 返回空文本")
    except Exception as exc:
        logs.append(f"OpenAI ASR 失败: {exc}")

    return chunks, logs


def _get_whisper_model(model_name: str) -> Any:
    key = model_name.strip().lower()
    if key in _WHISPER_MODELS:
        return _WHISPER_MODELS[key]
    from faster_whisper import WhisperModel  # type: ignore

    model = WhisperModel(key, device="cpu", compute_type="int8")
    _WHISPER_MODELS[key] = model
    return model


def _asr_with_local_whisper(audio_path: Path, model_name: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    logs: List[str] = []
    chunks: List[Dict[str, Any]] = []
    if not audio_path.exists():
        return chunks, logs

    try:
        model = _get_whisper_model(model_name)
        segments, info = model.transcribe(
            str(audio_path),
            language="zh",
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
            beam_size=5,
        )
        idx = 1
        for seg in segments:
            text = (seg.text or "").strip()
            if not text:
                continue
            chunks.append(
                {
                    "start": round(float(seg.start), 2),
                    "end": round(float(seg.end), 2),
                    "text": text,
                    "source": str(audio_path),
                    "line": idx,
                }
            )
            idx += 1
        logs.append(f"Local Whisper ASR 完成，模型={model_name}，语言={getattr(info, 'language', 'unknown')}")
    except Exception as exc:
        logs.append(f"Local Whisper ASR 失败: {exc}")

    return chunks, logs


def _build_evidence_from_ocr(ocr_hits: List[Dict[str, Any]], max_items: int = 10) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for hit in ocr_hits[:max_items]:
        out.append(
            {
                "type": "frame_ocr" if "frame" in hit["source"] else "cover_ocr",
                "source": hit["source"],
                "locator": hit.get("locator") or "",
                "snippet": hit["text"][:120],
                "confidence": hit.get("confidence", 0.5),
            }
        )
    return out


def _build_evidence_from_transcript(chunks: List[Dict[str, Any]], max_items: int = 10) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for c in chunks[:max_items]:
        locator = f"line:{c.get('line', '')}"
        if c.get("start") is not None:
            locator = f"{c.get('start')}s-{c.get('end')}s"
        out.append(
            {
                "type": "timestamp" if c.get("start") is not None else "transcript_span",
                "source": c.get("source", ""),
                "locator": locator,
                "snippet": c.get("text", "")[:120],
                "confidence": 0.7,
            }
        )
    return out


def _extract_from_info_json(
    files: List[Path],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str], Dict[str, Any]]:
    chunks: List[Dict[str, Any]] = []
    evidence: List[Dict[str, Any]] = []
    cover_text_candidates: List[str] = []
    post_content: Dict[str, Any] = {"title": "", "body": "", "tags": []}

    for info_path in files:
        try:
            data = read_json(info_path, default={})
        except Exception:
            continue
        title = str(data.get("title", "")).strip()
        description = str(data.get("description", "")).strip()
        tags = data.get("tags", []) if isinstance(data.get("tags", []), list) else []

        if not post_content["title"] and title:
            post_content["title"] = title
        if not post_content["body"] and description:
            post_content["body"] = description
        if not post_content["tags"] and tags:
            post_content["tags"] = [str(t) for t in tags]

        if title:
            cover_text_candidates.append(title[:80])
            chunks.append(
                {
                    "start": None,
                    "end": None,
                    "text": title[:300],
                    "source": str(info_path),
                    "line": 1,
                }
            )
            evidence.append(
                {
                    "type": "cover_ocr",
                    "source": str(info_path),
                    "locator": "field:title",
                    "snippet": title[:120],
                    "confidence": 0.62,
                }
            )
        if description:
            chunks.append(
                {
                    "start": None,
                    "end": None,
                    "text": description[:500],
                    "source": str(info_path),
                    "line": 2,
                }
            )
            evidence.append(
                {
                    "type": "transcript_span",
                    "source": str(info_path),
                    "locator": "field:description",
                    "snippet": description[:120],
                    "confidence": 0.55,
                }
            )
        if tags:
            tag_text = " ".join(str(t) for t in tags[:12])
            if tag_text:
                chunks.append(
                    {
                        "start": None,
                        "end": None,
                        "text": f"标签: {tag_text}"[:500],
                        "source": str(info_path),
                        "line": 3,
                    }
                )
                evidence.append(
                    {
                        "type": "visual_pattern",
                        "source": str(info_path),
                        "locator": "field:tags",
                        "snippet": tag_text[:120],
                        "confidence": 0.5,
                    }
                )
    return chunks, evidence, cover_text_candidates, post_content


def _cover_candidate_score(text: str, source: str = "") -> float:
    cleaned = _clean_ocr_text(text)
    if not cleaned:
        return -999.0

    cjk_count = sum(1 for ch in cleaned if "\u4e00" <= ch <= "\u9fff")
    alpha_count = sum(1 for ch in cleaned if ch.isalpha())
    digit_count = sum(1 for ch in cleaned if ch.isdigit())
    length = len(cleaned)

    score = float(cjk_count * 3 + digit_count * 0.3)
    if 4 <= length <= 32:
        score += 3.0
    elif length <= 3:
        score -= 6.0
    elif length > 50:
        score -= 2.0

    if cjk_count == 0 and alpha_count > 0:
        score -= 4.0
    if cleaned.lower() in {"nales", "prompt", "google"}:
        score -= 5.0

    source_lower = source.lower()
    if source_lower.endswith(".jpg") or source_lower.endswith(".png"):
        score += 1.5
    if "cover" in source_lower or "thumbnail" in source_lower:
        score += 1.0
    if ".info.json" in source_lower:
        score += 2.0
    return score


def _choose_cover_title(
    ocr_hits: List[Dict[str, Any]],
    post_content: Dict[str, Any],
    meta_cover: List[str],
) -> str:
    candidates: List[Tuple[float, str]] = []

    title = str(post_content.get("title", "")).strip()
    if title:
        candidates.append((_cover_candidate_score(title, "post_content.title") + 3.0, title[:80]))

    for item in meta_cover:
        cleaned = _clean_ocr_text(str(item))
        if cleaned:
            candidates.append((_cover_candidate_score(cleaned, "info.json"), cleaned[:80]))

    for hit in ocr_hits:
        if not isinstance(hit, dict):
            continue
        text = _clean_ocr_text(str(hit.get("text", "")).splitlines()[0])
        if not text:
            continue
        score = _cover_candidate_score(text, str(hit.get("source", ""))) + float(hit.get("confidence", 0.0) or 0.0)
        candidates.append((score, text[:80]))

    if not candidates:
        return ""

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _safe_page_number(path: Path, fallback: int) -> int:
    match = re.search(r"(\d+)", path.stem)
    if match:
        try:
            return int(match.group(1))
        except Exception:
            return fallback
    return fallback


def _page_visual_stats(path: Path) -> Dict[str, Any]:
    try:
        from PIL import Image, ImageStat  # type: ignore

        with Image.open(path) as img:
            rgb = img.convert("RGB")
            stat = ImageStat.Stat(rgb)
            grayscale = rgb.convert("L")
            gray_stat = ImageStat.Stat(grayscale)
            return {
                "width": rgb.width,
                "height": rgb.height,
                "brightness": round(float(sum(gray_stat.mean) / max(len(gray_stat.mean), 1)), 2),
                "stddev": round(float(sum(gray_stat.stddev) / max(len(gray_stat.stddev), 1)), 2),
                "color_channels": [round(float(x), 2) for x in stat.mean[:3]],
            }
    except Exception:
        return {"width": None, "height": None, "brightness": None, "stddev": None, "color_channels": []}


def _clean_ocr_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text


def _detect_invalid_reason(text: str, stats: Dict[str, Any]) -> str:
    cleaned = _clean_ocr_text(text)
    brightness = stats.get("brightness")
    stddev = stats.get("stddev")

    if not cleaned and brightness is not None and stddev is not None and brightness >= 240 and stddev <= 6:
        return "空白占位页"
    if cleaned and len(cleaned) <= 4 and brightness is not None and brightness >= 242 and stddev is not None and stddev <= 7:
        return "空白占位页"

    shell_markers = ["小红书", "发现", "消息", "发布", "我", "搜索", "关注", "购物", "服务"]
    if "小红书" in cleaned and sum(1 for item in shell_markers if item in cleaned) >= 3:
        return "公共壳页"
    return ""


def _classify_page_type(text: str, page_no: int, total_pages: int, invalid_reason: str) -> str:
    if invalid_reason:
        return "invalid"

    cleaned = _clean_ocr_text(text)
    if not cleaned:
        return "unknown"

    if page_no == 1:
        return "cover"

    if page_no >= max(2, total_pages - 1) and re.search(r"收藏|关注|评论|下篇|下一篇|想看|继续写|你想看", cleaned):
        return "cta"

    if re.search(r"风险|权限|边界|骗局|焦虑|成本|不要|别被|误区|陷阱|谨慎|警告", cleaned):
        return "risk"
    if re.search(r"截图|数据|证据|官方|新闻|研究|实验|报告", cleaned):
        return "evidence"
    if re.search(r"步骤|怎么|先|然后|第一|第二|第三|获取|操作|设置|生成|保存", cleaned):
        return "method"
    if re.search(r"案例|场景|比如|可以用来|工作流|翻译|写代码|整理|订票|订位", cleaned):
        return "scenario"
    if re.search(r"是什么|什么意思|理解成|等于|不是|本质|区别|就像|类似", cleaned):
        return "explanation"
    if page_no <= 2 or re.search(r"很多人|最近|我发现|先说|先讲|你以为|其实", cleaned):
        return "intro"
    return "unknown"


def _infer_design_elements(text: str, stats: Dict[str, Any], invalid_reason: str, page_type: str) -> List[str]:
    if invalid_reason:
        return [invalid_reason]

    cleaned = _clean_ocr_text(text)
    width = stats.get("width")
    height = stats.get("height")
    stddev = stats.get("stddev")
    elements: List[str] = []

    line_count = max(1, len([x for x in re.split(r"[。！？\n]", text or "") if x.strip()]))
    if line_count >= 4:
        elements.append("白底长文")
    else:
        elements.append("短文案强钩子")

    if re.search(r"=|vs|对比|区别|不是|而是", cleaned):
        elements.append("关键对比图")
    if re.search(r"截图|官网|界面|案例|工作流|插件|浏览器|终端|仪表盘", cleaned):
        elements.append("截图+文字混排")
    if re.search(r"水管|工厂|类比|示意|图解|像", cleaned):
        elements.append("概念示意图")
    if re.search(r"1\.|2\.|3\.|第一|第二|第三|步骤", cleaned):
        elements.append("步骤编号")
    if page_type in {"scenario", "method"} and "截图+文字混排" not in elements:
        elements.append("场景卡片")

    if width and height and height > width:
        elements.append("竖版页卡")
    if stddev is not None and stddev < 25:
        elements.append("大面积留白")

    deduped: List[str] = []
    seen = set()
    for item in elements:
        if item not in seen:
            deduped.append(item)
            seen.add(item)
    return deduped


def _page_conversion_goal(page_type: str, page_no: int, total_pages: int) -> str:
    mapping = {
        "cover": "点击后不退出",
        "intro": "降低理解门槛",
        "explanation": "讲清概念差异",
        "scenario": "建立价值感与收藏欲",
        "method": "给立即可执行动作",
        "evidence": "增强信任与说服力",
        "risk": "处理异议并激发评论",
        "cta": "引导收藏评论或追更",
        "unknown": "补充链路信息",
        "invalid": "无效页，不参与转化",
    }
    if page_no == total_pages and page_type == "unknown":
        return "引导收藏评论或追更"
    return mapping.get(page_type, "补充链路信息")


def _page_core_role(page_type: str, page_no: int, total_pages: int) -> str:
    mapping = {
        "cover": "建立标题预期和视觉钩子",
        "intro": "把技术问题翻译成用户痛点",
        "explanation": "用一句话或比喻讲清概念",
        "scenario": "证明这个内容能落到具体使用场景",
        "method": "把理解转成动作，降低起步成本",
        "evidence": "用外部证据托住观点，不让内容悬空",
        "risk": "处理风险、边界或反方视角，提高讨论度",
        "cta": "把用户推向收藏、评论或下一篇",
        "invalid": "公共壳页或空白帧，不属于正文",
        "unknown": "辅助链路推进",
    }
    if page_no == total_pages and page_type == "unknown":
        return "收束全文并承接下一步动作"
    return mapping.get(page_type, "辅助链路推进")


def _analyze_page_images(page_images: List[Path]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    page_analysis: List[Dict[str, Any]] = []
    page_ocr_hits: List[Dict[str, Any]] = []
    blank_or_shell_frames: List[Dict[str, Any]] = []
    total_pages = len(page_images)

    for fallback_no, image_path in enumerate(page_images, start=1):
        page_no = _safe_page_number(image_path, fallback_no)
        stats = _page_visual_stats(image_path)
        text, conf = _ocr_image(image_path)
        cleaned = _clean_ocr_text(text)
        invalid_reason = _detect_invalid_reason(cleaned, stats)
        page_type = _classify_page_type(cleaned, page_no, total_pages, invalid_reason)
        is_valid = not invalid_reason
        design_elements = _infer_design_elements(cleaned, stats, invalid_reason, page_type)

        if cleaned:
            page_ocr_hits.append(
                {
                    "source": str(image_path),
                    "locator": f"page:{page_no}",
                    "text": cleaned,
                    "confidence": conf,
                }
            )

        evidence = []
        if cleaned:
            evidence.append(
                {
                    "type": "frame_ocr",
                    "source": str(image_path),
                    "locator": f"page:{page_no}",
                    "snippet": cleaned[:180],
                    "confidence": conf or 0.55,
                }
            )
        evidence.append(
            {
                "type": "visual_pattern",
                "source": str(image_path),
                "locator": f"page:{page_no}",
                "snippet": ", ".join(design_elements[:4]) or "静态页卡",
                "confidence": 0.58,
            }
        )

        summary = cleaned[:160] if cleaned else (invalid_reason or "无有效文字")
        core_role = _page_core_role(page_type, page_no, total_pages)
        conversion_goal = _page_conversion_goal(page_type, page_no, total_pages)

        page_analysis.append(
            {
                "page": page_no,
                "source": str(image_path),
                "page_type": page_type,
                "is_valid": is_valid,
                "summary": summary,
                "core_role": core_role,
                "design_elements": design_elements,
                "conversion_goal": conversion_goal,
                "visual_stats": stats,
                "evidence": evidence,
            }
        )

        if invalid_reason:
            blank_or_shell_frames.append({"page": page_no, "source": str(image_path), "reason": invalid_reason})

    page_analysis.sort(key=lambda item: int(item.get("page", 0)))
    blank_or_shell_frames.sort(key=lambda item: int(item.get("page", 0)))
    return page_analysis, page_ocr_hits, blank_or_shell_frames


def main() -> int:
    args = parse_args()
    output_dir = ensure_dir(Path(args.output_dir).resolve())
    result_file = Path(args.result_file).resolve() if args.result_file else output_dir / "signals.json"

    fetch = read_json(Path(args.fetch_result).resolve(), default={})
    if not fetch.get("ok"):
        err = structured_error(
            "UPSTREAM_FETCH_FAILED",
            "fetch 结果不可用，无法提取信号",
            "先修复下载步骤，再重试 extract_signals.py",
            {"upstream": fetch.get("error")},
        )
        write_json(result_file, err)
        print(result_file)
        return 1

    asset_index = fetch.get("asset_index", {})
    post_content = fetch.get("post_content", {})
    engagement_metrics = fetch.get("engagement_metrics", {})
    videos = [Path(p) for p in asset_index.get("video", []) if Path(p).exists()]
    page_image_paths = [Path(p) for p in asset_index.get("page_images", []) if Path(p).exists()]
    page_image_set = {str(p.resolve()) for p in page_image_paths}
    images = [
        Path(p)
        for p in asset_index.get("images", [])
        if Path(p).exists() and str(Path(p).resolve()) not in page_image_set
    ]
    transcripts = [Path(p) for p in asset_index.get("transcript", []) if Path(p).exists()]
    artifact_all = [Path(p) for p in fetch.get("artifacts", {}).get("all_files", [])]
    info_json_files = [p for p in artifact_all if p.suffix.lower() == ".json" and p.name.endswith(".info.json") and p.exists()]

    frame_dir = ensure_dir(output_dir / "frames")
    ocr_hits: List[Dict[str, Any]] = []
    transcript_chunks: List[Dict[str, Any]] = []
    page_analysis: List[Dict[str, Any]] = []
    blank_or_shell_frames: List[Dict[str, Any]] = []
    logs: List[Any] = []
    generated_audio: List[str] = []
    ratio_info: Dict[str, Any] = {"value": "unknown", "width": None, "height": None, "confidence": 0.2}

    if videos:
        video_path = videos[0]
        width, height = _video_resolution(video_path)
        ratio_info = {
            "value": _aspect_ratio_label(width, height),
            "width": width,
            "height": height,
            "confidence": 0.92 if width and height else 0.2,
        }
        frames, frame_logs = _extract_frames(video_path, frame_dir)
        logs.extend(frame_logs)

        for idx, frame in enumerate(frames):
            text, conf = _ocr_image(Path(frame))
            if text:
                ocr_hits.append(
                    {
                        "source": frame,
                        "locator": f"frame:{idx}",
                        "text": text,
                        "confidence": conf,
                    }
                )

        audio_path = output_dir / "audio.wav"
        audio_log = _extract_audio(video_path, audio_path)
        logs.append(audio_log)
        if audio_path.exists() and audio_path.stat().st_size > 44:
            generated_audio.append(str(audio_path))
            asr_chunks, asr_logs = _asr_with_openai(audio_path)
            logs.extend(asr_logs)
            if not asr_chunks:
                local_chunks, local_logs = _asr_with_local_whisper(audio_path, args.whisper_model)
                asr_chunks = local_chunks
                logs.extend(local_logs)
            transcript_chunks.extend(asr_chunks)

    if images:
        for idx, image in enumerate(images[:10]):
            text, conf = _ocr_image(image)
            if text:
                ocr_hits.append(
                    {
                        "source": str(image),
                        "locator": f"image:{idx}",
                        "text": text,
                        "confidence": conf,
                    }
                )

    if page_image_paths:
        page_analysis, page_ocr_hits, blank_or_shell_frames = _analyze_page_images(page_image_paths)
        ocr_hits.extend(page_ocr_hits)
        logs.append(
            {
                "step": "page_analysis",
                "page_count": len(page_image_paths),
                "valid_pages": sum(1 for item in page_analysis if item.get("is_valid")),
                "invalid_pages": len(blank_or_shell_frames),
            }
        )

    for sub_path in transcripts:
        transcript_chunks.extend(_parse_subtitle_file(sub_path))

    meta_chunks, meta_evidence, meta_cover, post_content = _extract_from_info_json(info_json_files)
    transcript_chunks.extend(meta_chunks)
    if not post_content.get("title"):
        post_content = {
            "title": str(fetch.get("post_content", {}).get("title", "")),
            "body": str(fetch.get("post_content", {}).get("body", "")),
            "tags": fetch.get("post_content", {}).get("tags", []),
        }
    else:
        if not post_content.get("body"):
            post_content["body"] = str(fetch.get("post_content", {}).get("body", ""))
        if not post_content.get("tags"):
            post_content["tags"] = fetch.get("post_content", {}).get("tags", [])

    if not ratio_info.get("width") and images:
        try:
            from PIL import Image  # type: ignore

            with Image.open(images[0]) as img:
                w, h = img.size
            ratio_info = {
                "value": _aspect_ratio_label(w, h),
                "width": w,
                "height": h,
                "confidence": 0.88,
            }
        except Exception:
            pass

    cover_title = _choose_cover_title(ocr_hits, post_content, meta_cover)

    evidence = _build_evidence_from_ocr(ocr_hits) + _build_evidence_from_transcript(transcript_chunks) + meta_evidence
    subtitle_style = _infer_subtitle_style(transcript_chunks, ocr_hits)

    limitations: List[str] = []
    if not transcript_chunks:
        limitations.append("未提取到口播/字幕文本。")
    if not ocr_hits:
        limitations.append("未提取到有效 OCR 文本。")
    if page_image_paths and not any(item.get("is_valid") for item in page_analysis):
        limitations.append("已抓到小红书图文页卡，但未识别出有效正文页。")
    if fetch.get("meta", {}).get("content_type") == "image_post" and not page_image_paths:
        limitations.append("小红书图文未抓到逐页页卡，只能基于元数据做弱分析。")
    if all(engagement_metrics.get(key) is None for key in ("likes", "comments", "plays")):
        limitations.append("平台未返回点赞/评论/播放等互动数据，报告保持空值而不做猜测。")
    limitations.extend(
        [
            "OCR 与 ASR 质量依赖素材清晰度。",
            "如无网络，Local Whisper 首次模型下载可能失败。",
        ]
    )

    payload = {
        "ok": True,
        "meta": {
            **fetch.get("meta", {}),
            "signals_extracted_at": utc_now_iso(),
        },
        "asset_index": {
            **asset_index,
            "audio": sorted(list({*(asset_index.get("audio", [])), *generated_audio})),
            "cover_text": [cover_title] if cover_title else (meta_cover[:1] if meta_cover else []),
        },
        "post_content": {
            "title": str(post_content.get("title", "")),
            "body": str(post_content.get("body", "")),
            "tags": post_content.get("tags", []) if isinstance(post_content.get("tags", []), list) else [],
        },
        "engagement_metrics": engagement_metrics,
        "visual_specs": {
            "video_main_aspect_ratio": ratio_info,
            "subtitle_style_inference": subtitle_style,
        },
        "signals": {
            "ocr_hits": ocr_hits,
            "transcript_chunks": transcript_chunks,
            "evidence_pool": evidence,
            "hook_candidates": [c["text"] for c in transcript_chunks[:5]] or [h["text"] for h in ocr_hits[:3]],
            "page_analysis": page_analysis,
            "page_type_sequence": [item.get("page_type", "unknown") for item in page_analysis if item.get("is_valid")],
        },
        "blank_or_shell_frames": blank_or_shell_frames,
        "logs": logs,
        "limitations": limitations,
    }

    write_json(result_file, payload)
    print(result_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
