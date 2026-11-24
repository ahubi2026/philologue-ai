"""llm_client.py — Gemini / OpenAI 전환 및 데모(모의) 모드 통합 클라이언트

- 추가 SDK 설치 없이 Python 표준 라이브러리(urllib.request)로 Gemini / OpenAI REST API를 호출한다.
- API 키가 설정되지 않았거나 사용자가 데모 모드를 선택하면,
  소크라테스 6규칙과 독해 수준별 비계 흐름을 반영한 데모(모의) 응답을 생성한다.
"""
import json
import time
import urllib.error
import urllib.request

import config


def get_provider_status(provider: str) -> tuple[bool, str]:
    """지정 제공자의 사용 가능 여부와 상태 설명을 반환한다."""
    if provider == "demo":
        return True, "API 키 없이 테스트할 수 있는 모의 소크라테스 대화 모드"
    if provider == "gemini":
        if config.GEMINI_API_KEY:
            return True, f"Gemini 연결 준비됨 ({config.GEMINI_MODEL})"
        return False, "GEMINI_API_KEY 미설정 (자동으로 데모 모드로 동작)"
    if provider == "openai":
        if config.OPENAI_API_KEY:
            return True, f"OpenAI 연결 준비됨 ({config.OPENAI_MODEL})"
        return False, "OPENAI_API_KEY 미설정 (자동으로 데모 모드로 동작)"
    return False, "지원하지 않는 제공자"


def resolve_provider(preferred: str | None = None) -> tuple[str, str, str | None]:
    """실제 사용할 (provider, model_name, fallback_notice)를 결정한다."""
    choice = (preferred or config.DEFAULT_LLM_PROVIDER).strip().lower()
    if choice == "gemini":
        if config.GEMINI_API_KEY:
            return "gemini", config.GEMINI_MODEL, None
        return "demo", "demo-socratic-v1", "GEMINI_API_KEY가 설정되지 않아 데모(모의) 모드로 실행 중입니다."
    if choice == "openai":
        if config.OPENAI_API_KEY:
            return "openai", config.OPENAI_MODEL, None
        return "demo", "demo-socratic-v1", "OPENAI_API_KEY가 설정되지 않아 데모(모의) 모드로 실행 중입니다."
    return "demo", "demo-socratic-v1", None


class APIStatusError(RuntimeError):
    """HTTP 상태 코드를 보존하는 API 오류."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def _post_json(url: str, payload: dict, headers: dict, max_retries: int = 2) -> dict:
    data = json.dumps(payload).encode("utf-8")
    last_err: Exception | None = None
    for attempt in range(max_retries):
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=config.LLM_TIMEOUT_SECONDS) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")
            if e.code in (429, 503) and attempt + 1 < max_retries:
                time.sleep(1.0)
                continue
            if e.code == 503:
                last_err = APIStatusError(
                    503,
                    "구글 AI 서버에 일시적으로 사용자가 몰렸습니다(HTTP 503). 잠시 후 다시 보내 주세요.",
                )
            elif e.code == 429:
                last_err = APIStatusError(
                    429,
                    "무료 API 요청 한도를 잠시 초과했습니다(HTTP 429). 잠시 후 다시 시도해 주세요.",
                )
            else:
                last_err = APIStatusError(e.code, f"API 응답 오류 (HTTP {e.code}): {body[:240]}")
            break
        except TimeoutError:
            last_err = APIStatusError(
                504,
                "AI 서버 응답 시간이 초과되었습니다(Timeout). 예비 모델로 전환하거나 잠시 후 다시 시도해 주세요.",
            )
            break
        except urllib.error.URLError as e:
            if isinstance(e.reason, TimeoutError):
                last_err = APIStatusError(
                    504,
                    "AI 서버 응답 시간이 초과되었습니다(Timeout). 잠시 후 다시 시도해 주세요.",
                )
            else:
                last_err = RuntimeError(f"네트워크 연결 오류: {e.reason}")
            break
    raise last_err if last_err else RuntimeError("알 수 없는 API 오류가 발생했습니다.")


_EXCLUDED_MODEL_KEYWORDS = (
    "image", "tts", "live", "audio", "embedding", "imagen", "veo", "robotics", "computer-use", "vision",
)


def _discover_fallback_gemini_models(exclude: str) -> list[str]:
    """현재 API 키로 호출 가능한 텍스트 생성용 Gemini 예비 모델 목록을 조회한다."""
    url = "https://generativelanguage.googleapis.com/v1beta/models"
    req = urllib.request.Request(url, headers={"x-goog-api-key": config.GEMINI_API_KEY}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return [m for m in ("gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.6-flash", "gemini-3.5-flash") if m != exclude]

    candidates = []
    for item in data.get("models", []):
        methods = item.get("supportedGenerationMethods", [])
        if "generateContent" not in methods:
            continue
        name = item.get("name", "")
        short = name.removeprefix("models/")
        low = short.lower()
        if not low.startswith("gemini-") or short == exclude:
            continue
        if any(bad in low for bad in _EXCLUDED_MODEL_KEYWORDS):
            continue
        candidates.append(short)

    def _priority(m: str) -> tuple[int, str]:
        low = m.lower()
        # 혼잡이 적은 flash-lite 계열을 1순위, 다른 flash 계열을 2순위로 배치
        if "flash-lite" in low:
            return (0, m)
        if "flash" in low:
            return (1, m)
        return (2, m)

    # 최신 버전이 먼저 오도록 우선순위 정렬
    candidates.sort(key=lambda m: (_priority(m)[0], m), reverse=False)
    # 동일 그룹 내에서는 버전 숫자가 큰 모델이 먼저 오도록 조정
    lite = sorted([m for m in candidates if "flash-lite" in m.lower()], reverse=True)
    flash = sorted([m for m in candidates if "flash" in m.lower() and "flash-lite" not in m.lower()], reverse=True)
    others = sorted([m for m in candidates if "flash" not in m.lower()], reverse=True)
    return (lite + flash + others)[:5]


def _call_gemini_once(system_prompt: str, messages: list[dict], model_name: str) -> str:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_name}:generateContent"
    )
    contents = []
    for m in messages:
        role = "model" if m["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})

    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": {
            "temperature": 0.6,
            "maxOutputTokens": 1024,
        },
    }
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": config.GEMINI_API_KEY,
    }
    resp = _post_json(url, payload, headers)
    try:
        parts = resp["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts).strip()
        if not text:
            raise ValueError("빈 응답")
        return text
    except (KeyError, IndexError, ValueError) as e:
        raise RuntimeError(f"Gemini 응답 파싱 실패: {str(resp)[:240]}") from e


def _call_gemini(system_prompt: str, messages: list[dict], model_name: str) -> tuple[str, str]:
    """기본 모델 호출 후 503/504/429/404 발생 시 사용 가능한 예비 모델로 자동 전환한다."""
    retryable = (404, 429, 503, 504)
    try:
        return _call_gemini_once(system_prompt, messages, model_name), model_name
    except APIStatusError as first_err:
        if first_err.code not in retryable:
            raise
        tried = [model_name]
        last_err: Exception = first_err
        for alt in _discover_fallback_gemini_models(exclude=model_name):
            tried.append(alt)
            try:
                return _call_gemini_once(system_prompt, messages, alt), alt
            except APIStatusError as alt_err:
                last_err = alt_err
                if alt_err.code not in retryable:
                    raise
        raise RuntimeError(
            f"{last_err} (자동 시도한 모델: {', '.join(tried)})"
        ) from last_err


def _call_openai(system_prompt: str, messages: list[dict], model_name: str) -> str:
    url = "https://api.openai.com/v1/chat/completions"
    openai_messages = [{"role": "system", "content": system_prompt}]
    for m in messages:
        openai_messages.append({"role": m["role"], "content": m["content"]})

    payload = {
        "model": model_name,
        "messages": openai_messages,
        "temperature": 0.6,
        "max_tokens": 300,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.OPENAI_API_KEY}",
    }
    resp = _post_json(url, payload, headers)
    try:
        text = resp["choices"][0]["message"]["content"].strip()
        if not text:
            raise ValueError("빈 응답")
        return text
    except (KeyError, IndexError, ValueError) as e:
        raise RuntimeError(f"OpenAI 응답 파싱 실패: {str(resp)[:240]}") from e


def _snippet(text: str, limit: int = 34) -> str:
    clean = " ".join(text.strip().split())
    return clean if len(clean) <= limit else clean[:limit] + "…"


def _generate_demo_reply(
    *,
    book: dict,
    question: dict,
    first_answer: str,
    last_user_text: str | None,
    reading_level: str,
    turn_no: int,
    max_turns: int,
) -> str:
    """API 키 없이도 소크라테스 6원리·수준별 비계를 테스트할 수 있는 모의 응답기."""
    # 직접 답/요약 요구 시 Guardrail 테스트 대응
    if last_user_text and any(k in last_user_text for k in ("답 알려", "정답", "요약해", "대신 써")):
        return (
            "정답이나 요약을 제가 대신 말씀드리면 스스로 판단할 기회가 줄어들어요. "
            f"대신 『{book['title']}』에서 지금 질문과 가장 가깝다고 느낀 장면 한 곳을 먼저 떠올려 말해 줄 수 있나요?"
        )

    # 마지막 턴 마무리
    if turn_no >= max_turns:
        return (
            "지금까지 근거와 반대 관점까지 차근차근 잘 짚어 주었어요. "
            "처음에 적었던 1차 생각과 비교했을 때, 지금 내 최종 판단에서 가장 달라졌거나 더 단단해진 이유는 무엇인가요?"
        )

    # 첫 질문 (대화 시작) — 사고 단계(stage)와 독해 수준에 맞춰 자연스럽게 질문
    stage = question.get("stage", "해석")
    if turn_no == 0:
        quote = _snippet(first_answer)
        if stage == "나와 연결하기":
            if reading_level == "basic":
                return (
                    f"소중한 경험을 \"{quote}\"라고 나누어 주었네요. "
                    f"그 경험 속에서 가장 기억에 남는 순간은 언제였고, 『{book['title']}』의 이야기와 어떤 점이 닮아 보이나요?"
                )
            if reading_level == "advanced":
                return (
                    f"\"{quote}\"라는 개인적 성찰이 인상적입니다. "
                    f"그 경험에서 드러난 나만의 기준은 『{book['title']}』가 던지는 핵심 쟁점과 어떤 점에서 맞닿거나 충돌하나요?"
                )
            return (
                f"내 경험을 \"{quote}\"라고 솔직하게 적어 주었어요. "
                f"그때 그런 선택을 하게 된 가장 큰 이유는 무엇이었고, 『{book['title']}』 속 인물이라면 어떻게 반응했을까요?"
            )
        if stage == "반론·평가":
            if reading_level == "basic":
                return (
                    f"\"{quote}\"라는 입장을 분명히 적어 주었네요. "
                    "혹시 나와 반대되는 생각을 하는 친구가 있다면 어떤 이유를 들 수 있을까요?"
                )
            if reading_level == "advanced":
                return (
                    f"\"{quote}\"라는 평가가 흥미롭습니다. "
                    "그 판단이 설득력을 얻기 위해 전제하고 있는 가치 기준은 무엇이며, 어떤 반례에 가장 취약할까요?"
                )
            return (
                f"\"{quote}\"라고 판단해 주었어요. "
                "이 입장을 뒷받침하는 핵심 근거 한 가지와, 반대로 생각해 볼 만한 지점은 무엇일까요?"
            )
        if reading_level == "basic":
            return (
                f"처음 생각에 \"{quote}\"라고 적어 주었네요. "
                f"『{book['title']}』의 어느 장면이나 인물의 말 때문에 그렇게 생각하게 되었나요?"
            )
        if reading_level == "advanced":
            return (
                f"\"{quote}\"라는 1차 해석이 흥미롭습니다. "
                "그 판단이 설득력을 가지려면 어떤 핵심 근거와 전제가 먼저 인정되어야 할까요?"
            )
        return (
            f"1차 해석에서 \"{quote}\"라고 정리해 주었어요. "
            "이 생각을 가장 잘 보여 주는 책 속 장면은 무엇이고, 왜 그 장면이 근거가 된다고 보나요?"
        )

    quote = _snippet(last_user_text or first_answer)

    # 턴별 소크라테스 질문 흐름 (수준별 차등)
    if turn_no == 1:
        if reading_level == "basic":
            return (
                f"\"{quote}\"라고 짚어 주었네요. "
                "그 장면에서 인물은 어떤 선택을 했고, 그 선택이 이야기에 어떤 변화를 만들었나요?"
            )
        if reading_level == "advanced":
            return (
                f"\"{quote}\"라는 근거를 제시해 주었는데요. "
                "혹시 같은 장면을 전혀 다른 의도나 맥락으로 해석할 여지는 없을까요?"
            )
        return (
            f"\"{quote}\"라는 점이 인상적입니다. "
            "그 근거가 앞에서 말한 내 주장과 어떻게 이어지는지 한 문장으로 연결해 볼 수 있을까요?"
        )

    if turn_no == 2:
        if reading_level == "basic":
            return (
                f"\"{quote}\"라고 생각해 보니 또 다른 관점도 궁금해집니다. "
                "책 속 다른 인물이 이 장면을 보았다면 어떤 기분이 들었을까요?"
            )
        if reading_level == "advanced":
            return (
                f"\"{quote}\"라는 주장에는 숨어 있는 기준이 있어 보입니다. "
                "만약 반대 입장의 독자가 그 기준에 반례를 든다면, 어떤 반론이 가장 강할까요?"
            )
        return (
            f"\"{quote}\"라고 답해 주었네요. "
            "그렇다면 반대 입장에 선 사람이나 다른 인물은 이 판단에 어떻게 반박할 수 있을까요?"
        )

    # 3턴 이후: 논리적 귀결 및 자기 점검
    if reading_level == "basic":
        return (
            f"\"{quote}\"라는 설명이 점점 구체적이네요. "
            "지금까지 나눈 이야기를 떠올렸을 때, 처음 생각에서 조금이라도 바뀐 점이 있나요?"
        )
    if reading_level == "advanced":
        return (
            f"\"{quote}\"라는 기준을 책의 다른 장면이나 오늘날 우리 사회에도 그대로 적용한다면, "
            "어떤 예상치 못한 문제나 한계가 생길 수 있을까요?"
        )
    return (
        f"\"{quote}\"라는 관점까지 넓혀 보았네요. "
        "방금 이야기한 반론까지 함께 고려한다면, 처음의 1차 해석을 어떻게 수정하거나 보완하고 싶나요?"
    )


def generate_socratic_reply(
    *,
    system_prompt: str,
    messages: list[dict],
    preferred_provider: str | None,
    book: dict,
    question: dict,
    first_answer: str,
    reading_level: str,
    turn_no: int,
    max_turns: int,
) -> tuple[str, str, str | None]:
    """소크라테스 AI 응답을 생성해 (reply_text, actual_model_name, notice)를 반환한다."""
    provider, model_name, notice = resolve_provider(preferred_provider)

    if provider == "gemini":
        reply, used_model = _call_gemini(system_prompt, messages, model_name)
        return reply, f"gemini:{used_model}", notice

    if provider == "openai":
        reply = _call_openai(system_prompt, messages, model_name)
        return reply, f"openai:{model_name}", notice

    last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), None)
    reply = _generate_demo_reply(
        book=book,
        question=question,
        first_answer=first_answer,
        last_user_text=last_user if turn_no > 0 else None,
        reading_level=reading_level,
        turn_no=turn_no,
        max_turns=max_turns,
    )
    return reply, model_name, notice
