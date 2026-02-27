#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import wave
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
    videos = [Path(p) for p in asset_index.get("video", []) if Path(p).exists()]
    images = [Path(p) for p in asset_index.get("images", []) if Path(p).exists()]
    transcripts = [Path(p) for p in asset_index.get("transcript", []) if Path(p).exists()]
    artifact_all = [Path(p) for p in fetch.get("artifacts", {}).get("all_files", [])]
    info_json_files = [p for p in artifact_all if p.suffix.lower() == ".json" and p.name.endswith(".info.json") and p.exists()]

    frame_dir = ensure_dir(output_dir / "frames")
    ocr_hits: List[Dict[str, Any]] = []
    transcript_chunks: List[Dict[str, Any]] = []
    logs: List[Any] = []
    generated_audio: List[str] = []

    if videos:
        video_path = videos[0]
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

    for sub_path in transcripts:
        transcript_chunks.extend(_parse_subtitle_file(sub_path))

    meta_chunks, meta_evidence, meta_cover, post_content = _extract_from_info_json(info_json_files)
    transcript_chunks.extend(meta_chunks)

    cover_title = ""
    if ocr_hits:
        cover_title = ocr_hits[0]["text"].splitlines()[0][:80]

    evidence = _build_evidence_from_ocr(ocr_hits) + _build_evidence_from_transcript(transcript_chunks) + meta_evidence

    limitations: List[str] = []
    if not transcript_chunks:
        limitations.append("未提取到口播/字幕文本。")
    if not ocr_hits:
        limitations.append("未提取到有效 OCR 文本。")
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
            "title": post_content.get("title", ""),
            "body": post_content.get("body", ""),
            "tags": post_content.get("tags", []),
        },
        "signals": {
            "ocr_hits": ocr_hits,
            "transcript_chunks": transcript_chunks,
            "evidence_pool": evidence,
            "hook_candidates": [c["text"] for c in transcript_chunks[:5]] or [h["text"] for h in ocr_hits[:3]],
        },
        "logs": logs,
        "limitations": limitations,
    }

    write_json(result_file, payload)
    print(result_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
