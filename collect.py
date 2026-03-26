"""
ESL AI Tracker — 수집 스크립트 (API 방식)
Gemini API · OpenAI API · Anthropic API 로 50개 질문을 던지고
기업 언급 횟수를 집계한 후 Firebase Realtime Database에 저장합니다.

설치:
    pip install requests google-generativeai openai anthropic

환경변수 설정 (로컬 실행 시 .env 또는 직접 export):
    GEMINI_API_KEY=...
    OPENAI_API_KEY=...
    ANTHROPIC_API_KEY=...

사용법:
    python collect.py              # 오늘 날짜로 수집
    python collect.py 2026-03-30  # 특정 날짜 지정
"""

import sys
import os
import json
import re
import time
import requests
from datetime import date
from collections import defaultdict

# ── 설정 ────────────────────────────────────────────────────────────────────
FIREBASE_DB     = "https://esl-weekly-report-default-rtdb.asia-southeast1.firebasedatabase.app"
FIREBASE_SECRET = os.environ.get("FIREBASE_SECRET", "HRsPR80bFHi6RlgxSf22DWdYOcDok78Obg2dPyWC")

GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY", "")
OPENAI_API_KEY    = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# API 호출 간 딜레이 (초) — rate limit 방지
CALL_DELAY = 2.0

# ── 기업명 정규화 ────────────────────────────────────────────────────────────
NORMALIZE = {
    "vusion":          "VusionGroup",
    "vusiongroup":     "VusionGroup",
    "vusion group":    "VusionGroup",
    "ses-imagotag":    "VusionGroup",
    "ses imagotag":    "VusionGroup",
    "pricer ab":       "Pricer AB",
    "pricer":          "Pricer AB",
    "hanshow":         "Hanshow",
    "solum":           "SoluM",
    "soluM":           "SoluM",
    "displaydata":     "Displaydata",
    "e ink holdings":  "E Ink Holdings",
    "e ink":           "E Ink Holdings",
    "eink":            "E Ink Holdings",
    "zkong":           "Zkong",
    "minewtag":        "Minewtag",
    "teraoka":         "Teraoka-DIGI",
    "teraoka-digi":    "Teraoka-DIGI",
    "teraoka/digi":    "Teraoka-DIGI",
    "digi":            "Teraoka-DIGI",
    "m2comm":          "M2COMM",
    "ncr":             "NCR",
    "ncr voyix":       "NCR",
    "captana":         "Captana",
    "opticon":         "Opticon",
    "avery dennison":  "Avery Dennison",
    "avery":           "Avery Dennison",
}

# ── 수집 질문 50개 ───────────────────────────────────────────────────────────
QUESTIONS = [
    # 시장 리더십
    "What are the leading companies in the Electronic Shelf Label (ESL) market?",
    "Who are the top ESL vendors globally by market share?",
    "Which company is the market leader in digital price tags?",
    "What are the best ESL solutions for large-scale retail deployment?",
    "Who dominates the electronic shelf label industry in Europe?",

    # AI·기술 기능
    "Which companies provide AI-powered electronic shelf labels?",
    "What ESL vendors support NFC-enabled smart labels for retail?",
    "Which ESL companies offer cloud-based label management platforms?",
    "Who are the leading providers of IoT-connected electronic shelf labels?",
    "What companies make e-paper electronic shelf labels for retail?",

    # 지역 시장
    "Who are the top ESL vendors in the Asia-Pacific market?",
    "Which companies lead the North American electronic shelf label market?",
    "What ESL companies are expanding in the Middle East and Africa?",
    "Who are the key players in the South Korean ESL market?",
    "Which companies lead ESL deployments in grocery retail in Europe?",

    # 버티컬 / 산업
    "Which ESL companies focus on pharmaceutical retail digital labeling?",
    "What electronic shelf label solutions are used in DIY and home improvement stores?",
    "Who provides ESL systems for convenience stores and forecourt retail?",
    "Which companies supply ESL solutions to fashion and apparel retailers?",
    "What ESL vendors support warehouse and logistics labeling?",

    # 경쟁 비교
    "How does SoluM compare to VusionGroup in ESL technology?",
    "What are the differences between Pricer and Hanshow ESL systems?",
    "Which ESL company offers the longest battery life for shelf labels?",
    "Who provides the most cost-effective ESL solution for mid-sized retailers?",
    "What company offers the widest range of ESL display sizes?",

    # 파트너십·채택
    "Which ESL companies have partnerships with major retail chains?",
    "What supermarket chains use electronic shelf labels from SoluM?",
    "Which retailers have deployed VusionGroup ESL solutions at scale?",
    "What are the largest ESL deployments in the world?",
    "Which ESL vendor has the most retail customer references in Europe?",

    # 기업 현황·전략
    "What are the latest innovations from electronic shelf label companies?",
    "Which ESL companies went public or raised significant funding recently?",
    "What is SoluM's strategy in the global ESL market?",
    "How is VusionGroup positioning itself in AI-driven retail technology?",
    "What are the growth plans of Hanshow in international markets?",

    # 표준·통신
    "Which ESL companies support 2.4GHz and Sub-GHz communication protocols?",
    "What ESL vendors offer solutions compatible with major ERP systems?",
    "Which companies provide ESL solutions with integration for SAP retail?",
    "What are the key ESL players supporting Bluetooth Low Energy (BLE) labels?",
    "Which companies make ESL gateways and infrastructure for large stores?",

    # 시장 트렌드·전망
    "What companies are driving growth in the electronic shelf label market in 2025?",
    "Which ESL vendors are leading the transition from LCD to e-paper displays?",
    "What are the emerging ESL companies challenging established market leaders?",
    "How are ESL companies addressing sustainability in their product lines?",
    "Which companies are pioneering color e-paper ESL displays?",

    # 종합·추천
    "If a retailer wants to implement ESL, which companies should they evaluate?",
    "What are the top 5 ESL companies a global grocery chain should consider?",
    "Which ESL company has the best customer support and service network?",
    "What ESL vendor is most recommended for high-volume grocery deployments?",
    "Which companies are considered innovators in the smart retail label space?",
]


# ── 언급 횟수 집계 ────────────────────────────────────────────────────────────
def count_mentions(text: str) -> dict:
    """AI 응답 텍스트에서 기업 언급 횟수를 카운트합니다."""
    counts = defaultdict(int)
    text_lower = text.lower()
    for keyword, canonical in NORMALIZE.items():
        pattern = r'\b' + re.escape(keyword) + r'\b'
        matches = re.findall(pattern, text_lower)
        if matches:
            counts[canonical] += len(matches)
    return dict(counts)


# ── Gemini API 수집 ───────────────────────────────────────────────────────────
def collect_gemini(questions: list) -> dict:
    """Gemini 2.0 Flash API로 수집"""
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY 환경변수가 설정되지 않았습니다")

    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.0-flash")

    counts = defaultdict(int)
    for i, q in enumerate(questions, 1):
        try:
            response = model.generate_content(q)
            text = response.text or ""
            mentions = count_mentions(text)
            for co, n in mentions.items():
                counts[co] += n
            print(f"  [{i}/{len(questions)}] 완료 — {sum(mentions.values())}회 언급")
        except Exception as e:
            print(f"  [{i}/{len(questions)}] 오류: {e}")
        time.sleep(CALL_DELAY)

    return dict(counts)


# ── OpenAI (ChatGPT) API 수집 ─────────────────────────────────────────────────
def collect_chatgpt(questions: list) -> dict:
    """GPT-4o API로 수집"""
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY 환경변수가 설정되지 않았습니다")

    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)

    counts = defaultdict(int)
    for i, q in enumerate(questions, 1):
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": q}],
                max_tokens=1024,
                temperature=0.3,
            )
            text = response.choices[0].message.content or ""
            mentions = count_mentions(text)
            for co, n in mentions.items():
                counts[co] += n
            print(f"  [{i}/{len(questions)}] 완료 — {sum(mentions.values())}회 언급")
        except Exception as e:
            print(f"  [{i}/{len(questions)}] 오류: {e}")
        time.sleep(CALL_DELAY)

    return dict(counts)


# ── Anthropic (Claude) API 수집 ───────────────────────────────────────────────
def collect_claude(questions: list) -> dict:
    """Claude Sonnet API로 수집"""
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다")

    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    counts = defaultdict(int)
    for i, q in enumerate(questions, 1):
        try:
            message = client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=1024,
                messages=[{"role": "user", "content": q}],
            )
            text = message.content[0].text or ""
            mentions = count_mentions(text)
            for co, n in mentions.items():
                counts[co] += n
            print(f"  [{i}/{len(questions)}] 완료 — {sum(mentions.values())}회 언급")
        except Exception as e:
            print(f"  [{i}/{len(questions)}] 오류: {e}")
        time.sleep(CALL_DELAY)

    return dict(counts)


# ── Firebase 저장 ────────────────────────────────────────────────────────────
def save_record(record: dict) -> bool:
    date_str = record["date"]
    url = f"{FIREBASE_DB}/ai-tracker/records/{date_str}.json?auth={FIREBASE_SECRET}"
    r = requests.put(url, json=record, timeout=10)
    if r.status_code == 200:
        return True
    else:
        print(f"  Firebase 응답: {r.status_code} — {r.text[:200]}")
        return False


# ── 메인 ─────────────────────────────────────────────────────────────────────
def main():
    collect_date = sys.argv[1] if len(sys.argv) > 1 else str(date.today())
    print(f"=== ESL AI Tracker 수집 시작: {collect_date} ===\n")

    record = {
        "date": collect_date,
        "questions": len(QUESTIONS),
    }

    # Gemini 수집
    print("▶ Gemini 2.0 Flash 수집 중...")
    try:
        gemini_data = collect_gemini(QUESTIONS)
        record["gemini"] = gemini_data
        print(f"  ✅ 완료: 총 {sum(gemini_data.values())}회 언급\n")
    except ValueError as e:
        print(f"  ⚠️  SKIP: {e}\n")
    except Exception as e:
        print(f"  ❌ ERROR: {e}\n")
        record["gemini_error"] = str(e)

    # ChatGPT 수집
    print("▶ ChatGPT (GPT-4o) 수집 중...")
    try:
        chatgpt_data = collect_chatgpt(QUESTIONS)
        record["chatgpt"] = chatgpt_data
        print(f"  ✅ 완료: 총 {sum(chatgpt_data.values())}회 언급\n")
    except ValueError as e:
        print(f"  ⚠️  SKIP: {e}\n")
    except Exception as e:
        print(f"  ❌ ERROR: {e}\n")
        record["chatgpt_error"] = str(e)

    # Claude 수집
    print("▶ Claude (Sonnet) 수집 중...")
    try:
        claude_data = collect_claude(QUESTIONS)
        record["claude"] = claude_data
        print(f"  ✅ 완료: 총 {sum(claude_data.values())}회 언급\n")
    except ValueError as e:
        print(f"  ⚠️  SKIP: {e}\n")
    except Exception as e:
        print(f"  ❌ ERROR: {e}\n")
        record["claude_error"] = str(e)

    # Firebase 저장
    print("▶ Firebase 저장 중...")
    ok = save_record(record)
    if ok:
        print(f"✅ {collect_date} 레코드가 저장되었습니다\n")
        print("저장된 데이터:")
        print(json.dumps(record, ensure_ascii=False, indent=2))
    else:
        print("❌ Firebase 저장 실패 — 네트워크 및 Secret 키를 확인해주세요")
        sys.exit(1)


if __name__ == "__main__":
    main()
