import os
import glob
import time
import calendar
import urllib.parse
import requests
import feedparser
from datetime import datetime, timedelta, timezone
from google import genai

# 1. API 키 확인 및 클라이언트 초기화
api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    raise ValueError("GEMINI_API_KEY가 설정되지 않았습니다.")

client = genai.Client(api_key=api_key)

# 2. 지정된 5대 파트 중심 정밀 수집 키워드
KEYWORDS = [
    "부동산", "아파트 분양", "대출 규제",
    "소비자물가", "한국은행 금리", "환율",
    "국회 본회의 법안", "정부 정책 시행령",
    "보건의료 의대", "건강보험 필수의료",
    "미국 연준 금리", "국제 유가 통상"
]

def fetch_news():
    collected_articles = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    for kw in KEYWORDS:
        query = urllib.parse.quote(kw)
        url = f"https://news.google.com/rss/search?q={query}+when:1d&hl=ko&gl=KR&ceid=KR:ko"
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            feed = feedparser.parse(resp.content)
            # 키워드당 6개 수집 (12개 키워드 x 6 = 약 72개 기사 확보)
            for entry in feed.entries[:6]:
                source = entry.source.title if hasattr(entry, 'source') else "언론사"
                collected_articles.append({
                    "keyword": kw,
                    "title": entry.title,
                    "source": source
                })
        except Exception as e:
            print(f"[{kw}] 수집 건너뜀: {e}")
            
    return collected_articles

def call_gemini(system_instruction, user_query):
    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model="gemini-3.8-flash",
                contents=user_query,
                config=genai.types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.0
                )
            )
            return response.text
        except Exception as e:
            wait_time = (attempt + 1) * 15
            print(f"API 호출 지연 ({attempt + 1}/{max_retries}). {wait_time}초 대기 후 재시도: {e}")
            if attempt < max_retries - 1:
                time.sleep(wait_time)
            else:
                raise e

def generate_daily_report(news_data, sys_prompt):
    news_list_text = f"수집 기준 일시: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n[수집된 뉴스 데이터 목록]\n"
    for idx, item in enumerate(news_data, 1):
        news_list_text += f"{idx}. [{item['keyword']}] {item['title']} (언론사: {item['source']})\n"

    user_query = (
        "리포트 주기: 데일리\n\n"
        "아래 수집된 뉴스 목록을 바탕으로 진보/보수 언론사 교차 검증을 거쳐, "
        "부동산, 물가, 정책, 보건의료, 해외이슈 5개 파트 중심의 데일리 시사 인텔리전스 리포트를 작성해 주세요.\n"
        "단순 단신 나열을 지양하고 배경과 파급 효과, 쟁점 대립 구도를 명확히 서술해 주세요.\n\n"
        f"{news_list_text}"
    )
    return call_gemini(sys_prompt, user_query)

def generate_weekly_report(sys_prompt, now_kst):
    print(">> 일요일 감지: 주간 데일리 리포트 취합 및 위클리 리포트 생성 시작...")
    combined_text = ""
    for i in range(6, -1, -1):
        target_date = (now_kst - timedelta(days=i)).strftime("%Y%m%d")
        matched_files = sorted(glob.glob(f"reports/daily_{target_date}_*.md"))
        if matched_files:
            latest_file = matched_files[-1]
            with open(latest_file, "r", encoding="utf-8") as f:
                combined_text += f"\n\n--- [Daily Report: {target_date}] ---\n" + f.read()
    
    if not combined_text:
        print("취합할 데일리 리포트가 없어 위클리 생성을 건너뜁니다.")
        return

    user_query = (
        "리포트 주기: 위클리\n\n"
        "아래는 지난 일주일간 수집·분석된 일자별 데일리 리포트 모음입니다.\n"
        "한 주간 발생한 주요 정책, 부동산, 물가, 보건의료, 해외 이슈의 누적 흐름과 "
        "사회적 파급력 및 중기적 주시 포인트를 종합하여 위클리 시사 분석 리포트를 작성해 주세요.\n\n"
        f"{combined_text}"
    )
    
    report = call_gemini(sys_prompt, user_query)
    today_date = now_kst.strftime("%Y%m%d")
    weekly_path = f"reports/week_{today_date}.md"
    with open(weekly_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f">> 위클리 리포트 저장 완료: {weekly_path}")

def generate_monthly_report(sys_prompt, now_kst):
    print(">> 말일 감지: 당월 데일리 리포트 취합 및 먼슬리 리포트 생성 시작...")
    current_month_prefix = now_kst.strftime("%Y%m")
    
    day_files = {}
    for f in sorted(glob.glob(f"reports/daily_{current_month_prefix}*.md")):
        filename = os.path.basename(f)
        date_key = filename.split("_")[1]
        day_files[date_key] = f

    if not day_files:
        print("취합할 당월 데일리 리포트가 없어 먼슬리 생성을 건너뜁니다.")
        return

    combined_text = ""
    for date_key in sorted(day_files.keys()):
        file_path = day_files[date_key]
        with open(file_path, "r", encoding="utf-8") as f:
            combined_text += f"\n\n--- [Daily Report: {date_key}] ---\n" + f.read()

    user_query = (
        "리포트 주기: 먼슬리\n\n"
        "아래는 이번 한 달간 누적된 데일리 시사 리포트 종합 데이터입니다.\n"
        "한 달간의 정부 정책 변화, 부동산/물가 사이클, 보건의료 및 해외 지정학 지형 변화를 총괄 평가하고 "
        "다음 달에 예정된 주요 입법 및 정책 변수를 정리한 월간 종합 시사 인텔리전스 리포트를 작성해 주세요.\n\n"
        f"{combined_text}"
    )
    
    report = call_gemini(sys_prompt, user_query)
    monthly_path = f"reports/months_{current_month_prefix}.md"
    with open(monthly_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f">> 먼슬리 리포트 저장 완료: {monthly_path}")

if __name__ == "__main__":
    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst)
    
    with open("system_prompt.txt", "r", encoding="utf-8") as f:
        sys_prompt = f.read()
        
    os.makedirs("reports", exist_ok=True)
    
    # 1. 데일리 리포트 (daily_YYYYMMDD_HHMM.md)
    print("1. 데일리 시사 뉴스 수집 및 리포트 작성...")
    news = fetch_news()
    daily_report = generate_daily_report(news, sys_prompt)
    
    timestamp_minute = now_kst.strftime("%Y%m%d_%H%M")
    daily_path = f"reports/daily_{timestamp_minute}.md"
    with open(daily_path, "w", encoding="utf-8") as f:
        f.write(daily_report)
    print(f"데일리 리포트 저장 완료: {daily_path}")
    
    # 2. 위클리 체크 (일요일 -> week_YYYYMMDD.md)
    if now_kst.weekday() == 6:
        generate_weekly_report(sys_prompt, now_kst)
        
    # 3. 먼슬리 체크 (말일 -> months_YYYYMM.md)
    last_day_of_month = calendar.monthrange(now_kst.year, now_kst.month)[1]
    if now_kst.day == last_day_of_month:
        generate_monthly_report(sys_prompt, now_kst)
