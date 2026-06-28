from __future__ import annotations

import base64
import json
import mimetypes
import os
import time
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import requests

from common import ensure_runtime_env
from repair_json import extract_json


SKILL_ROOT = Path(__file__).resolve().parents[1]
PROMPTS_DIR = SKILL_ROOT / "prompts"


def _env(name: str, default: str | None = None) -> str | None:
    ensure_runtime_env()
    value = os.environ.get(name)
    return value if value else default


def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / name
    return path.read_text(encoding="utf-8")


def _data_url(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    mime = mime or "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _json_headers(api_key: str, *, bearer: bool = True, extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {api_key}"
    else:
        headers["Authorization"] = api_key
    if extra:
        headers.update(extra)
    return headers


def _parse_jsonish(text: str) -> dict[str, Any]:
    return extract_json(text)


def _google_file_state(file_obj: dict[str, Any]) -> str:
    state = file_obj.get("state")
    if isinstance(state, dict):
        return str(state.get("name", ""))
    return str(state or "")


def _google_upload_file(
    path: Path,
    *,
    api_key: str,
    base_url: str | None = None,
    timeout: int = 300,
) -> dict[str, Any]:
    mime, _ = mimetypes.guess_type(path.name)
    mime = mime or "application/octet-stream"
    base = (base_url or _env("GEMINI_BASE_URL") or "https://generativelanguage.googleapis.com").rstrip("/")
    parsed = urlparse(base)
    if parsed.path.rstrip("/") in {"", "/v1beta"}:
        upload_base = f"{parsed.scheme}://{parsed.netloc}"
        api_base = f"{parsed.scheme}://{parsed.netloc}/v1beta"
    else:
        upload_base = f"{parsed.scheme}://{parsed.netloc}"
        api_base = base
    start = requests.post(
        f"{upload_base}/upload/v1beta/files",
        params={"key": api_key},
        headers={
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(path.stat().st_size),
            "X-Goog-Upload-Header-Content-Type": mime,
            "Content-Type": "application/json",
        },
        json={"file": {"display_name": path.name}},
        timeout=timeout,
    )
    start.raise_for_status()
    upload_url = start.headers.get("X-Goog-Upload-URL") or start.headers.get("x-goog-upload-url")
    if not upload_url:
        raise RuntimeError("Gemini upload start did not return an upload URL")
    finalize = requests.post(
        upload_url,
        headers={
            "Content-Length": str(path.stat().st_size),
            "X-Goog-Upload-Offset": "0",
            "X-Goog-Upload-Command": "upload, finalize",
        },
        data=path.read_bytes(),
        timeout=timeout,
    )
    finalize.raise_for_status()
    file_obj = finalize.json().get("file") or finalize.json()
    file_name = file_obj.get("name")
    if not file_name:
        raise RuntimeError("Gemini file upload did not return a file name")
    for _ in range(120):
        status = requests.get(f"{api_base}/{file_name}", params={"key": api_key}, timeout=timeout)
        status.raise_for_status()
        current = status.json()
        state = _google_file_state(current)
        if state == "ACTIVE":
            return current
        if state == "FAILED":
            raise RuntimeError(f"Gemini file processing failed: {current}")
        time.sleep(2)
    raise RuntimeError(f"Gemini file did not become ACTIVE in time: {file_name}")


def _google_delete_file(
    file_name: str,
    *,
    api_key: str,
    base_url: str | None = None,
    timeout: int = 120,
) -> None:
    base = (base_url or _env("GEMINI_BASE_URL") or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
    response = requests.delete(f"{base}/{file_name}", params={"key": api_key}, timeout=timeout)
    if response.status_code not in {200, 204, 404}:
        response.raise_for_status()


def openai_chat_json(
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    api_key: str | None = None,
    base_url: str | None = None,
    temperature: float = 0.2,
    schema: dict[str, Any] | None = None,
    timeout: int = 300,
) -> dict[str, Any]:
    key = api_key or _env("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    endpoint = (base_url or _env("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    response = requests.post(endpoint, headers=_json_headers(key), json=payload, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    content = data["choices"][0]["message"].get("content", "")
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    if not content:
        raise RuntimeError("OpenAI returned empty content")
    return _parse_jsonish(str(content))


def openai_chat_text(
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    api_key: str | None = None,
    base_url: str | None = None,
    temperature: float = 0.2,
    timeout: int = 300,
) -> str:
    key = api_key or _env("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    endpoint = (base_url or _env("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    response = requests.post(endpoint, headers=_json_headers(key), json=payload, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    content = data["choices"][0]["message"].get("content", "")
    return content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)


def openai_vision_json(
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    image_paths: Iterable[Path],
    api_key: str | None = None,
    base_url: str | None = None,
    temperature: float = 0.2,
    schema: dict[str, Any] | None = None,
    timeout: int = 300,
) -> dict[str, Any]:
    key = api_key or _env("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    endpoint = (base_url or _env("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
    content: list[dict[str, Any]] = [{"type": "text", "text": user_prompt}]
    for image_path in image_paths:
        content.append({"type": "image_url", "image_url": {"url": _data_url(Path(image_path)), "detail": "high"}})
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
    }
    response = requests.post(endpoint, headers=_json_headers(key), json=payload, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    content = data["choices"][0]["message"].get("content", "")
    if isinstance(content, list):
        content = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
    if not content:
        raise RuntimeError("OpenAI returned empty content")
    return _parse_jsonish(str(content))


def openai_transcribe(
    audio_path: Path,
    *,
    model: str,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: int = 300,
) -> str:
    key = api_key or _env("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    endpoint = (base_url or _env("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/") + "/audio/transcriptions"
    with Path(audio_path).open("rb") as handle:
        response = requests.post(
            endpoint,
            headers={"Authorization": f"Bearer {key}"},
            files={"file": handle},
            data={"model": model, "response_format": "text"},
            timeout=timeout,
        )
    response.raise_for_status()
    return response.text.strip().strip('"')


def _decode_openai_image_payload(item: dict[str, Any]) -> bytes:
    b64 = item.get("b64_json")
    if b64:
        return base64.b64decode(b64)
    url = item.get("url")
    if url:
        response = requests.get(url, timeout=300)
        response.raise_for_status()
        return response.content
    raise RuntimeError(f"OpenAI image response did not contain b64_json or url: {item}")


def openai_generate_image(
    *,
    model: str,
    prompt: str,
    size: str,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: int = 300,
) -> bytes:
    key = api_key or _env("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    endpoint = (base_url or _env("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/") + "/images/generations"
    payload = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "n": 1,
    }
    response = requests.post(endpoint, headers=_json_headers(key), json=payload, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    items = data.get("data") or []
    if not items:
        raise RuntimeError(f"OpenAI image generation returned no data: {data}")
    return _decode_openai_image_payload(items[0])


def openai_edit_image(
    *,
    model: str,
    prompt: str,
    image_paths: Iterable[Path],
    size: str,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: int = 300,
) -> bytes:
    key = api_key or _env("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    endpoint = (base_url or _env("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/") + "/images/edits"
    files: list[tuple[str, tuple[str, Any, str]]] = []
    handles = []
    try:
        for image_path in image_paths:
            path = Path(image_path)
            mime, _ = mimetypes.guess_type(path.name)
            mime = mime or "image/png"
            handle = path.open("rb")
            handles.append(handle)
            files.append(("image[]", (path.name, handle, mime)))
        response = requests.post(
            endpoint,
            headers={"Authorization": f"Bearer {key}"},
            data={
                "model": model,
                "prompt": prompt,
                "size": size,
                "n": "1",
            },
            files=files,
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        items = data.get("data") or []
        if not items:
            raise RuntimeError(f"OpenAI image edit returned no data: {data}")
        return _decode_openai_image_payload(items[0])
    finally:
        for handle in handles:
            handle.close()


def gemini_generate_json(
    *,
    model: str,
    prompt: str,
    parts: list[dict[str, Any]],
    api_key: str | None = None,
    base_url: str | None = None,
    temperature: float = 0.2,
    schema: dict[str, Any] | None = None,
    timeout: int = 300,
) -> dict[str, Any]:
    key = api_key or _env("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    base = (base_url or _env("GEMINI_BASE_URL") or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
    endpoint = f"{base}/models/{model}:generateContent"
    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}, *parts]}],
        "generationConfig": {
            "temperature": temperature,
            "responseMimeType": "application/json",
        },
    }
    if schema:
        payload["generationConfig"]["responseSchema"] = schema

    response = requests.post(
        endpoint,
        params={"key": key},
        headers={"Content-Type": "application/json"},
        json=payload,
        timeout=timeout,
    )
    if response.status_code == 400 and schema:
        fallback_payload = {
            "contents": payload["contents"],
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "application/json",
            },
        }
        response = requests.post(
            endpoint,
            params={"key": key},
            headers={"Content-Type": "application/json"},
            json=fallback_payload,
            timeout=timeout,
        )
    response.raise_for_status()
    data = response.json()
    text = data["candidates"][0]["content"]["parts"][0].get("text", "")
    if not text:
        raise RuntimeError("Gemini returned empty content")
    return _parse_jsonish(text)


def gemini_video_json(
    *,
    model: str,
    prompt: str,
    video_path: Path,
    api_key: str | None = None,
    base_url: str | None = None,
    temperature: float = 0.2,
    schema: dict[str, Any] | None = None,
    timeout: int = 300,
) -> dict[str, Any]:
    key = api_key or _env("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    uploaded = _google_upload_file(Path(video_path), api_key=key, base_url=base_url, timeout=timeout)
    file_name = uploaded.get("name")
    file_uri = uploaded.get("uri")
    mime = uploaded.get("mimeType") or uploaded.get("mime_type") or "video/mp4"
    if not file_uri:
        raise RuntimeError("Gemini file upload did not return a file URI")
    try:
        return gemini_generate_json(
            model=model,
            prompt=prompt,
            parts=[
                {
                    "file_data": {
                        "mime_type": mime,
                        "file_uri": file_uri,
                    }
                }
            ],
            api_key=key,
            base_url=base_url,
            temperature=temperature,
            schema=schema,
            timeout=timeout,
        )
    finally:
        if file_name:
            try:
                _google_delete_file(file_name, api_key=key, base_url=base_url)
            except Exception:
                pass


def _fal_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Key {api_key}",
        "Content-Type": "application/json",
    }


def fal_run_json(
    *,
    endpoint_id: str,
    payload: dict[str, Any],
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: int = 300,
    poll_interval_s: float = 2.0,
    max_polls: int = 180,
    start_retries: int = 3,
) -> dict[str, Any]:
    key = api_key or _env("BFL_API_KEY") or _env("FLUX_API_KEY")
    if not key:
        raise RuntimeError("FAL/FLUX API key is not configured")
    base = (base_url or _env("BFL_BASE_URL") or _env("FLUX_BASE_URL") or "https://fal.run").rstrip("/")
    endpoint = f"{base}/{endpoint_id.lstrip('/')}"
    last_error: Exception | None = None
    response = None
    for attempt in range(start_retries):
        try:
            response = requests.post(endpoint, headers=_fal_headers(key), json=payload, timeout=timeout)
            response.raise_for_status()
            break
        except requests.exceptions.RequestException as exc:
            last_error = exc
            if attempt == start_retries - 1:
                raise
            time.sleep(min(2 * (attempt + 1), 5))
    if response is None:
        raise RuntimeError(f"fal start request did not produce a response: {last_error}")
    data = response.json()
    if any(key_name in data for key_name in ("images", "video", "audio")):
        return data
    status_url = data.get("status_url") or data.get("response_url") or response.headers.get("Location")
    if not status_url:
        return data
    for _ in range(max_polls):
        try:
            poll = requests.get(status_url, headers=_fal_headers(key), timeout=timeout)
            poll.raise_for_status()
        except requests.exceptions.RequestException:
            time.sleep(poll_interval_s)
            continue
        poll_data = poll.json()
        state = str(poll_data.get("status", "")).lower()
        if any(key_name in poll_data for key_name in ("images", "video", "audio")):
            return poll_data
        if state in {"completed", "complete", "succeeded", "success", "done"}:
            return poll_data.get("output", poll_data)
        if state in {"failed", "error", "cancelled"}:
            raise RuntimeError(f"fal task failed: {poll_data}")
        time.sleep(poll_interval_s)
    raise TimeoutError(f"fal task did not finish after {max_polls} polls: {status_url}")


def byteplus_seedance_run(
    *,
    model: str,
    prompt: str,
    image_urls: list[str],
    duration: int,
    aspect_ratio: str,
    resolution: str,
    api_key: str | None = None,
    base_url: str | None = None,
    watermark: bool = False,
    generate_audio: bool = False,
    timeout: int = 300,
    poll_interval_s: float = 5.0,
    max_polls: int = 120,
) -> dict[str, Any]:
    key = api_key or _env("ARK_API_KEY") or _env("SEEDANCE_API_KEY")
    if not key:
        raise RuntimeError("ARK_API_KEY / SEEDANCE_API_KEY is not configured")
    raw_base = (base_url or _env("ARK_BASE_URL") or _env("SEEDANCE_BASE_URL") or "https://ark.cn-beijing.volces.com").rstrip("/")
    base = raw_base if raw_base.endswith("/api/v3") else f"{raw_base}/api/v3"
    endpoint = f"{base}/contents/generations/tasks"
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for url in image_urls:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": url},
                "role": "reference_image",
            }
        )
    payload = {
        "model": model,
        "content": content,
        "ratio": aspect_ratio,
        "duration": int(duration),
        "resolution": resolution,
        "watermark": bool(watermark),
        "generate_audio": bool(generate_audio),
    }
    create_response = requests.post(
        endpoint,
        headers=_json_headers(key),
        json=payload,
        timeout=timeout,
    )
    if create_response.status_code == 401:
        raise RuntimeError(
            "Seedance video generation returned 401 Unauthorized. "
            "Please verify that the current ARK/SEEDANCE key has access to the official "
            "Volcengine Ark Seedance video-generation route and the configured model."
        )
    create_response.raise_for_status()
    created = create_response.json()
    task_id = created.get("id")
    if not task_id:
        if created.get("status") in {"succeeded", "success"}:
            return created
        raise RuntimeError(f"Seedance task creation did not return id: {created}")
    status_url = f"{endpoint}/{task_id}"
    for _ in range(max_polls):
        poll = requests.get(status_url, headers=_json_headers(key), timeout=timeout)
        poll.raise_for_status()
        poll_data = poll.json()
        status = str(poll_data.get("status", "")).lower()
        if status in {"succeeded", "success", "completed", "complete", "done"}:
            return poll_data
        if status in {"failed", "error", "cancelled"}:
            raise RuntimeError(f"Seedance task failed: {poll_data}")
        time.sleep(poll_interval_s)
    raise TimeoutError(f"Seedance task did not finish after {max_polls} polls: {task_id}")


def volcengine_las_seedance_run(
    *,
    operator_id: str,
    payload: dict[str, Any],
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: int = 300,
) -> dict[str, Any]:
    key = api_key or _env("LAS_API_KEY")
    if not key:
        raise RuntimeError("LAS_API_KEY is not configured")
    base = (base_url or _env("LAS_BASE_URL") or "https://operator.las.cn-beijing.volces.com/api/v1").rstrip("/")
    endpoint = f"{base}/{operator_id.lstrip('/')}"
    response = requests.post(
        endpoint,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        json=payload,
        timeout=timeout,
    )
    if response.status_code == 401:
        raise RuntimeError(
            "Volcengine LAS video-model request returned 401 Unauthorized. "
            "Please configure a China-mainland video-model LAS_API_KEY from the "
            "Volcengine AI Data Lake / video-model console, not an Ark text-model key."
        )
    response.raise_for_status()
    return response.json()


def elevenlabs_tts(
    text: str,
    *,
    voice_id: str | None = None,
    model_id: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: int = 300,
) -> bytes:
    key = api_key or _env("ELEVENLABS_API_KEY")
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY is not configured")
    voice = voice_id or _env("ELEVENLABS_VOICE_ID") or "21m00Tcm4TlvDq8ikWAM"
    model = model_id or _env("ELEVENLABS_TTS_MODEL") or "eleven_multilingual_v2"
    base = (base_url or _env("ELEVENLABS_BASE_URL") or "https://api.elevenlabs.io/v1").rstrip("/")
    endpoint = f"{base}/text-to-speech/{voice}"
    response = requests.post(
        endpoint,
        headers={
            "xi-api-key": key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        json={
            "text": text,
            "model_id": model,
            "output_format": "mp3_44100_128",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.content
