# 필로로그 AI — 클라우드 웹 배포 가이드 (Streamlit Community Cloud + Supabase)

학생 10~15명 시범수업을 위해 **영구 클라우드 DB(Supabase PostgreSQL)**와 **Streamlit Community Cloud**에 배포하는 절차입니다.
*(로컬 PC에서 실행할 때는 `DATABASE_URL`이 비어 있으므로 자동으로 기존 SQLite로 동작합니다.)*

---

## 1단계. Supabase 클라우드 DB 만들기 (무료)
1. [https://supabase.com](https://supabase.com) 에 접속해 로그인합니다.
2. **New project** 클릭 → 이름 예: `philologue-ai`, 비밀번호 설정, Region은 **Northeast Asia (Seoul)** 선택 후 생성합니다.
3. 프로젝트가 준비되면 상단 **Connect** 버튼 → **Connection string** → **Transaction pooler (포트 6543)** URI를 복사합니다.
   - 형태 예시: `postgresql://postgres.[프로젝트ID]:[설정한비밀번호]@aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres`
   - 비밀번호에 특수문자(`@`, `#`, `/` 등)가 들어가면 URL 인코딩 문제가 생길 수 있으므로 **영문+숫자 조합** 비밀번호를 권장합니다.

---

## 2단계. GitHub 비공개(Private) 저장소에 올리기
1. GitHub에서 새 저장소를 **Private(비공개)**으로 만듭니다(예: `philologue-ai`).
2. `g:\jey\Dissertation_Article\philologue\` 폴더의 파일들을 업로드(push)합니다.
   - `.gitignore`가 이미 설정되어 있어 **`.env` 파일과 로컬 테스트 DB(`data/philologue.db`)는 자동으로 제외**됩니다.
   - 웹 업로드 시에는 `.env`와 `data/philologue.db`를 직접 빼고 올리세요.

---

## 3단계. Streamlit Community Cloud에 배포하기
1. [https://share.streamlit.io](https://share.streamlit.io) 에 GitHub 계정으로 로그인합니다.
2. **Create app** → 방금 만든 GitHub 저장소와 브랜치 선택 → **Main file path**에 `app.py` 입력.
3. **Advanced settings** 클릭:
   - **Python version**: `3.11` 또는 `3.12` 선택
   - **Secrets** 입력란에 아래 TOML을 붙여넣고 실제 값으로 채웁니다:

```toml
PHILOLOGUE_LLM_PROVIDER = "gemini"
GEMINI_API_KEY = "여기에_Gemini_API_키"
GEMINI_MODEL = "gemini-flash-lite-latest"
PHILOLOGUE_MAX_TURNS = "8"
PHILOLOGUE_TEACHER_CODE = "우리수업만의_비밀코드"
DATABASE_URL = "여기에_Supabase_Transaction_Pooler_URI"
```

4. **Deploy!** 버튼을 누르면 1~2분 뒤 접속 주소(`https://....streamlit.app`)가 생성됩니다.

---

## 4단계. 첫 접속 및 시범수업 시작
1. 배포된 주소로 접속 → **회원가입** 탭 → 하단 **`👩‍🏫 교사·연구자 계정으로 가입하기`**를 펼쳐 `Secrets`에 넣은 `PHILOLOGUE_TEACHER_CODE`를 입력해 교사 계정을 생성합니다.
2. 교사 계정으로 로그인하면 대시보드 상단에 **`☁️ 클라우드 DB (PostgreSQL / Supabase)`**가 표시됩니다.
3. 이제 학생들에게 배포 링크를 안내하고 별명 회원가입 후 수업을 진행하면 모든 기록이 Supabase에 안전하게 영구 저장됩니다.
4. 매 차시 종료 직후 **`📊 연구용 CSV 내보내기`** 탭에서 4종 CSV를 내려받아 이중 백업하세요.
