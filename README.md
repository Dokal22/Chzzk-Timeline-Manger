# 치지직 타임라인 매니저 (Chzzk-Timeline-Manager)

치지직(CHZZK) 다시보기(VOD)의 음성 데이터와 실시간 채팅 화력을 분석하여, ChatGPT 구독으로 로그인한 Codex 기반 하이라이트 타임라인 초안을 생성하는 도구입니다. 생성 결과를 직접 수정한 뒤 치지직에 게시할 수 있습니다.

---

* ## [⚙️ 주요 설정으로 이동](#️-configjson-설정)

* ## [🛠️ Prompt 커스텀으로 이동](#️-prompt-커스텀)

* ## [⚠️ 주의사항](#️-주의사항-1)

# ✨ 프로젝트 개요

이 프로젝트는 방송 전체 흐름 속에서:

* 스트리머 발언
* 시청자 반응
* 채팅 화력 집중 구간
* 주요 방송 흐름

을 동시에 분석하여 타임라인을 생성합니다.

핵심 기능:

* Faster-Whisper 기반 음성 전사(STT)
* 채팅 화력 분석 및 노이즈 제거
* Codex 구조화 요약
* 스트리머 발언 기준 싱크 보정
* 댓글로 게시하기 전 타임라인 초안을 직접 수정

---

# 🚀 주요 기능

## 🎵 VOD 오디오 및 채팅 수집

* yt-dlp 기반 고속 오디오 다운로드
* yt-dlp 실패 시 CHZZK 공식 playback API로 직접 오디오 스트림 조회, 그래도 실패하면 `ChzzkVideoDownloader.exe`(CLI)로 최종 폴백하는 3단계 구조
* 다운로드 캐싱 지원
* 치지직 채팅 전체 로그 저장
* 특정 구간(%)만 선택 분석 가능

---

## 🧠 Faster-Whisper 기반 STT

* CUDA GPU 자동 사용
* CPU fallback 지원
* 긴 방송 자동 슬라이싱 처리
* 한국어 고정밀 음성 전사

---

## 🔥 채팅 화력 분석

다음 요소를 기반으로 하이라이트를 탐지합니다.

* 채팅 밀도
* 폭발 반응 구간
* 반복 반응 빈도
* 감정 반응 집중도

자동 정제 대상:

* 과도한 ㅋㅋㅋ / ㅎㅎㅎ
* 반복 도배
* 특수문자 이모티콘
* 무의미한 스팸 텍스트

---

## 🤖 Codex 기반 타임라인 생성

Codex가 다음 구조로 방송 내용을 정리합니다.

```text
[대주제; 소주제]
[타임스탬프] 내용
```

예시:

```text
[저스트 채팅; 방송 시작]
[00:03:05] 인사 및 방송 컨디션 이야기

[게임; 랭크 시작]
[01:12:33] 경쟁전 큐 시작 및 팀원 반응
```

---

## 💬 타임라인 초안 수정 및 게시

타임라인은 `TL_VOD_...txt` 파일로 저장되며 댓글에 자동 등록되지 않습니다. 파일을 직접 수정하거나 메뉴 2번으로 기본 텍스트 편집기에서 연 다음, 내용을 복사해 치지직 VOD 댓글 입력창에 붙여넣고 직접 게시하세요.

---

# 📄 파일 설명

## Main.py

CLI 인터페이스 및 전체 실행 흐름 담당

* 모드 선택
* 사용자 입력 처리
* 타임라인 초안 생성 및 열기

---

## Timeline.py

핵심 AI 처리 모듈

* 오디오 다운로드
* Whisper 전사
* Codex 분석
* 타임라인 생성

---

## Chzzk_api.py

치지직/네이버 API 처리

* VOD 조회
* 채팅 수집
* 채팅 정제
* 화력 분석

---

## config.json

* 환경 설정 파일

저장소 루트의 [`config.example.json`](config.example.json)을 `config.json`으로
복사하고 값을 입력하세요. 앱은 현재 작업 폴더의 `config.json`을 읽으므로 아래 실행
명령도 저장소 루트에서 사용합니다. 치지직 로그인 쿠키는 설정 파일에 넣지 않고,
가능한 경우 로그인한 브라우저에서 자동으로 찾습니다.

---

## 준비된 재료로 타임라인만 다시 만들기

메인 메뉴에서 `[2] 준비된 재료로 타임라인만 다시 만들기`를 선택하면 오디오 다운로드와 Whisper STT 변환을 건너뛰고 Codex 타임라인 생성부터 다시 실행합니다.

선택한 VOD에 다음 두 파일이 모두 있어야 합니다.

* `voicepalette/VOD_<VOD_ID>/full_raw_script.txt`
* `chat_cache/<VOD_ID>/chat_<VOD_ID>_full.txt`

재료가 없거나 비어 있으면 일반 생성 모드로 자동 전환하지 않고 누락된 경로를 안내한 뒤 중단합니다. 먼저 `[1]` 모드를 실행해 재료를 준비해 주세요.

## 시간 구간만 분석하기

VOD를 선택한 뒤 퍼센트 대신 `MM:SS` 또는 `HH:MM:SS` 형식으로 분석 시작·종료 시간을 입력합니다. 예를 들어 `01:10:00`부터 `01:45:30`까지 입력하면 일반 생성 모드는 해당 구간의 오디오만 ffmpeg로 추출하고, 그 구간만 Whisper STT와 Codex 타임라인 생성에 사용합니다.

구간 오디오와 대본은 각각 `range_audio_<시작초>_<종료초>.ts`, `raw_script_<시작초>_<종료초>.txt`로 저장되어 전체 VOD 캐시와 섞이지 않습니다. 대본의 타임스탬프는 잘라낸 파일 기준 `00:00:00`이 아니라 원본 VOD의 절대 시간으로 유지됩니다. 시작과 종료를 비워 전체 범위를 선택하면 기존 `full_vod_audio.ts`와 `full_raw_script.txt` 캐시를 그대로 사용합니다.

---

# ⚙️ config.json 설정

## 예시

전체 설정 예제는 저장소 루트의 [`config.example.json`](config.example.json)을
복사해 사용하세요. 프롬프트 기능 관련 기본값은 아래와 같습니다.

```json
{
    "TARGET_CHANNEL_ID": "치지직_32자리_채널_해시값",
    "CODEX_MODEL": "",
    "WHISPER_LANGUAGE": "ko",
    "WHISPER_MODEL": "base",
    "DIARIZATION_ENABLED": false,
    "DIARIZATION_MODEL": "pyannote/speaker-diarization-community-1",
    "DIARIZATION_DEVICE": "auto",
    "PROMPT_RESEARCH_ENABLED": false,
    "PROMPT_DEBUG_MODE": "off",
    "PROMPT_DEBUG_LINES": 10,
    "NAMUWIKI_PROFILE_ENABLED": false,
    "REFERENCE_ENABLED": false,
    "REFERENCE_DIR": "references",
    "REFERENCE_URLS": [],
    "REFERENCE_CACHE_DIR": "reference_cache"
}
```

이 값들은 기존 `config.json`의 최상위 객체 안에 추가하거나 필요에 따라 바꾸세요.

### 채널 해시값 추출 방법

1. 치지직에서 해시값을 찾고자 하는 스트리머의 채널(홈)로 이동합니다.
2. `https://chzzk.naver.com/(이 부분에 영문과 숫자로 된 긴 코드가 있습니다)`

예시)

`https://chzzk.naver.com/abc123xyz45667890faeebccddeeff12`

해시값: `abc123xyz45667890faeebccddeeff12`

### Codex 구독 로그인 방법

1. Codex CLI를 설치합니다: `npm install -g @openai/codex`
2. 터미널에서 `codex login`을 실행합니다.
3. 브라우저에서 이 프로젝트에 사용할 ChatGPT 구독 계정으로 로그인합니다.
4. `codex login status`로 로그인 상태를 확인합니다.

`CODEX_MODEL`을 빈 문자열로 두면 Codex CLI의 기본 모델을 사용합니다. 특정 모델이 구독 계정에서 제공되는 경우에만 모델 이름을 지정하세요. API 키는 필요하지 않습니다.

---

# 🧠 WHISPER_MODEL 설명

| 모델       | 속도    | 정확도   | 특징       |
| -------- | ----- | ----- | -------- |
| tiny     | 매우 빠름 | 낮음    | 저사양용     |
| base     | 빠름    | 보통    | 기본 추천    |
| small    | 빠름    | 준수    | 밸런스형     |
| medium   | 보통    | 좋음    | 방송 분석 추천 |
| large-v3 | 느림    | 매우 높음 | 최고 정확도   |
| turbo    | 매우 빠름 | 높음    | 최신 고성능   |

추천:

* 빠른 테스트: `base`, `small`
* 고품질 분석: `medium`, `turbo`

일반 생성 모드에서 모델을 실행마다 선택할 수 있으며 Enter는 설정값을 씁니다.
준비된 재료로 타임라인만 다시 만들 때는 STT 설정 질문을 건너뜁니다. 선택한
모델·언어별 전사 결과는 별도 캐시에 저장되므로 옵션을 바꾸면 다시 전사합니다.

## 선택형 화자 분리

화자 분리를 켜면 pyannote가 발화 구간에 익명 `SPEAKER_00`, `SPEAKER_01` 등의
표시를 붙입니다. 이 번호는 사람의 실명이나 스트리머 이름을 뜻하지 않습니다.
여러 화자가 한 전사 구간에 비슷한 시간 동안 겹치면 `SPEAKER_MIXED`, 매칭되지
않으면 `UNKNOWN`으로 표시합니다. 긴 VOD에서는 별도 분석 시간이 들며 GPU 메모리나
CPU 자원을 사용합니다. 화자 분리는 FFmpeg로 오디오를 16 kHz mono 파형으로 디코딩해
모델에 직접 전달하므로 Windows의 TorchCodec FFmpeg DLL 로딩을 우회합니다. 선택한
분석 구간 전체를 파형으로 메모리에 올리므로 매우 긴 방송은 분석 범위를 좁혀 실행하는
편이 좋습니다.

기본 설치에는 화자 분리 라이브러리가 포함되지 않습니다. Python 3.10 이상 환경에서
선택 기능용 패키지를 설치하고, Hugging Face에서 모델 이용 조건에 직접 동의한 뒤
읽기 토큰을 프로젝트 루트 `.env`의 `HF_TOKEN` 항목이나 환경 변수에 설정하세요.
`.env`는 Git에서 제외됩니다. 토큰을 `config.json`에 넣지 마세요.

```powershell
pip install -r requirements-diarization.txt
```

`DIARIZATION_DEVICE`는 `auto`(기본값), `cuda`, `cpu` 중 하나입니다. `auto`는
PyTorch CUDA를 사용할 수 있으면 GPU를 선택하고, 아니면 CPU 선택 사유를 출력합니다.
`cuda`는 CUDA 미지원 PyTorch 환경에서 VOD를 받기 전에 중단하며, GPU 이동/추론
실패 시 CPU로 조용히 전환하지 않고 CPU 재시도 또는 중단을 묻습니다. CUDA를 쓰려면
앱도 CUDA 지원 PyTorch가 설치된 동일한 Python 환경으로 실행해야 합니다.

Windows에서 기존 전역 Python을 바꾸지 않고 전용 환경을 준비하려면 저장소 루트에서:

```powershell
py -3.12 -m venv .venv-gpu
.\.venv-gpu\Scripts\python.exe -m pip install --upgrade pip
.\.venv-gpu\Scripts\python.exe -m pip install -r requirements.txt
.\.venv-gpu\Scripts\python.exe -m pip install -r requirements-diarization.txt
.\.venv-gpu\Scripts\python.exe -m pip install --upgrade --force-reinstall torch==2.12.0 --index-url https://download.pytorch.org/whl/cu126
.\.venv-gpu\Scripts\python.exe scripts\check_diarization_gpu.py
```

CUDA wheel을 설치한 같은 Python으로 앱을 실행하세요. 이후 `requirements.txt` 설치나
업그레이드가 torch를 CPU wheel로 바꾸지 않았는지 진단 스크립트로 확인할 수 있습니다.
이 저장소의 앱 진입점은 다음과 같습니다.

```powershell
.\.venv-gpu\Scripts\python.exe src\code\Main.py
```

프로젝트 루트 `.env` 파일 예시:

```dotenv
HF_TOKEN=hf_실제읽기토큰
```

또는 현재 PowerShell 창에만 적용하려면 `$env:HF_TOKEN = "hf_실제읽기토큰"`을 설정한 뒤 실행하세요.

모델 다운로드/인증/추론이 실패하면 원인을 표시하고, 화자 구분 없이 계속할지
선택할 수 있습니다. 실패한 diarization은 성공 캐시로 기록되지 않습니다.

---

# 🛠️ Prompt 커스텀

저장소 루트에 아래 파일을 두어 프롬프트 및 채널별 참고 정보를 관리할 수 있습니다.

## streamer_profiles/<치지직_채널_ID>.txt

채널별 스트리머 정보 및 밈 보정용 사용자 프로필입니다. 방송 주인공 이름은
이 파일에 고정하지 않고, `TARGET_CHANNEL_ID`로 조회한 선택 VOD의 실제 채널명을
사용합니다. 프로필은 반드시 채널 ID별 파일로 관리되며, 다른 채널의 정보가
섞이지 않습니다.

예시:

```text
[방송 정보]
- 스트리머: 담유이
- 팬덤: 아담이
- 주요 콘텐츠: 저스트 채팅, FPS 게임
```

활용 목적:

* STT 오타 보정
* 밈 인식
* 합방 멤버 구분
* 고유명사 정확도 향상

예시:

```text
[방송인 기본 정보]
- 스트리머 이름: 예시스트리머
- 팬덤 이름: 예시팬덤
- 주요 방송 콘텐츠: 저스트 채팅, 종합 게임

[콘텐츠별 페르소나]
- 콘텐츠: 예시 역할극 서버
- 게임/서버: 예시 게임
- 캐릭터명: 예시캐릭터
- 실제 스트리머: 예시스트리머
- 활성화 키워드: 예시 역할극 서버, 예시캐릭터
- 적용 제외: 방송 공지, 기술 문제, 일반 시청자 소통
```

채널 ID별 프로필이 있고 파일 안의 스트리머 이름이 실제 VOD 채널명과 일치하면
해당 파일을 사용합니다. 이름이 다르면 해당 프로필을 무시합니다. 루트의
`streamer_info.txt`는 채널을 식별할 수 없어 production owner 프로필로
사용하지 않습니다. 둘 다 없거나 이름이 다르면 API에서 확인한 채널명과 채널
ID만 기본 정보로 전달하므로 다른 스트리머의 설명이 섞이지 않습니다.

합방 멤버/닉네임 보정 목록은 별도 전역 DB인 `chzzk_streamers.txt`를 사용합니다.
이 파일은 owner 프로필과 다른 기능이며 채널별 프로필 파일에 합치지 않습니다.

`[콘텐츠별 페르소나]`는 공식 스트리머의 보조 정체성을 정의합니다. 예를 들어
공식 스트리머가 `뇨롱이`이고 봉누도2 캐릭터가 `아마도`라면, 봉누도2·아마도·
인생서버 등의 키워드가 현재 VOD 제목·STT·채팅에서 확인되는 청크에서만
페르소나 후보로 전달됩니다. 일반 소통, 공지, 기술 문제, 다른 콘텐츠에서는
공식 스트리머명을 사용합니다. 프로필에 이름만 적혀 있고 현재 입력에 근거가
없으면 페르소나를 활성화하지 않습니다.

VOD를 선택하면 프로필 사용 방식을 묻습니다.

* `Enter` 또는 `y`: 기존 캐시 사용. 캐시가 없으면 공식 CHZZK 채널 API에서
  채널명과 공식 설명을 조사해 최초 프로필 생성
* `n`: 이번 실행에서는 스트리머 프로필을 사용하지 않음
* `update` 또는 `u`: 공식 CHZZK 채널 API를 다시 조회해 프로필 갱신

`config.json`의 `NAMUWIKI_PROFILE_ENABLED`를 `true`로 명시적으로 켜면, 공식 CHZZK
채널명이 확인된 뒤 동일 이름의 나무위키 문서를 보수적으로 확인하여 방송 관련
허용 섹션만 추가 캐시합니다. robots 정책, 리다이렉트, 문서 식별, 필터링 중 하나라도
실패하면 공식 정보만 저장합니다. 논란·사건/사고·사생활 등 민감한 내용은 허용
섹션 안에서도 결정적으로 제외하며, 나무위키 원문 전체는 저장하지 않습니다.
나무위키 참고 내용은 갱신 시 channel-scoped
`streamer_profiles/<채널_ID>.knowledge.json` entity index로 저장합니다. 기존
`.txt`는 공식 CHZZK identity/description과 사용자 persona만 유지하며, 나무위키
일반 소개나 대규모 게임 목록을 붙이지 않습니다. index는 게임·콘텐츠·캐릭터·별명
같은 intact phrase와 출처 section/context만 보관합니다. 타임라인 청크에는 현재
VOD 제목·STT·채팅에서 exact phrase가 확인된 최대 8개 record, 1,500자까지만
전달됩니다. profile/index만으로 현재 방송 사건이나 플레이를 추론하지 않고,
현재 STT·채팅·제목을 항상 우선합니다.

갱신에 실패하면 기존 프로필을 유지합니다. 조사 결과는
`streamer_profiles/<채널_ID>.meta.json`에 출처 URL, 조사 시각, 채널명 및
해시와 함께 기록됩니다. 공식 CHZZK 정보가 항상 권위 있는 출처이며, 나무위키 내용은
비신뢰 참고자료로만 Codex에 전달됩니다.

## 선택형 참고자료 (reference pipeline)

HTML 참고 URL은 원본 응답을 최대 1 MiB까지 streaming으로 제한해 수집하고,
정제 텍스트와 최종 prompt context는 기존 300 KiB 제한을 유지합니다. h1~h6
heading으로 섹션화한 뒤 현재 VOD 제목·STT·채팅과 lexical match되는 섹션만
청크별로 전달합니다. 논란·사건/사고·평가·흥행·여담·외부 링크 섹션은 제외되며,
참고자료는 현재 사건이나 참여자의 근거가 아니라 고유명사·관계·상황 해석용입니다.

`config.json`에서 아래 옵션을 켜면 VOD 전체 STT 전사 후 참고자료를 한 번
읽은 뒤 heading section index로 캐시하고, 각 1시간 분석 청크의 제목·STT·채팅과
연관된 section만 검색해 전달합니다. 기본값은 꺼져 있습니다.

```json
{
  "REFERENCE_ENABLED": false,
  "REFERENCE_DIR": "references",
  "REFERENCE_URLS": [],
  "REFERENCE_CACHE_DIR": "reference_cache"
}
```

`REFERENCE_DIR`에는 `.txt`, `.md`, `.json`, `.csv` 파일과 Windows 인터넷
바로가기 `.url`을 둘 수 있습니다. `.url`은 `[InternetShortcut]` 섹션의
`URL=https://...` 값만 읽으며 바로가기를 실행하지 않습니다. URL은 직접
지정된 `http`/`https` 주소만 읽고, 검색·크롤링·페이지 내부 링크 추적은
하지 않습니다.

파일은 최대 5개(파일당 100KB, 로컬 합계 300KB), URL은 최대 3개(응답당
1MiB, 추출 텍스트 합계/최종 context 300KB)까지 제한됩니다. PDF/DOCX, 로그인 페이지,
JavaScript 렌더링 페이지는 지원하지 않습니다. 참고자료는 고유명사와
상황 해석을 보조하는 비신뢰 데이터이며, 실제 사건과 시간은 STT·채팅을
우선합니다. 참고자료 로드에 실패해도 기존 타임라인 분석은 계속됩니다.

URL 참고자료는 `reference_cache/`에 URL별 SHA-256 키 JSON으로 저장됩니다.
`REFERENCE_ENABLED`가 `true`이면 유효한 캐시가 있는 URL마다 실행 중에
기존 캐시를 사용할지 업데이트할지 묻습니다. 캐시가 없으면 최초 다운로드를
진행합니다. 업데이트는 ETag/Last-Modified 조건부 요청으로 시도하며, 업데이트
실패 시 기존 캐시로 복귀합니다. 원본 HTML이 아닌 정제 section record만 최대
450 logical lines로 저장하며 JSON은 사람이 검토할 수 있도록 여러 줄로 기록합니다.
HTML 표·목록의 셀은 항목별 줄바꿈으로 보존하고, 하위 문서 링크만 있는 섹션은
제외합니다. 각 섹션에는 방송 요약 우선순위를 위한 `A/B/C` relevance 등급이 붙습니다.
실제 분석 청크에는 최대 10개 record, 6,000자/12,000 UTF-8 bytes까지만
전달됩니다. 파서 버전이 바뀐 오래된 캐시는 자동 갱신을 시도하고, 네트워크 갱신에
실패하면 기존 캐시로 복귀합니다.

## prompt.txt (기존 추가 지침 가져오기)

AI 행동 지침

예시:

```text
- 반복 표현 최소화
- 게임명 정확히 표기
- 핵심 장면 위주 정리
```

프롬프트 레지스트리가 아직 없을 때 `prompt.txt`가 있으면 내용을 가져와 타임라인 분석
구간으로 등록합니다. 독립된 `[제목]` 줄은 구간 제목으로 분리됩니다. 레지스트리가 만들어진
뒤에는 `prompt.txt`를 매번 다시 읽지 않으므로 이후 내용은 실행 메뉴 `[4]`에서 편집하세요.

실행 메뉴의 `[4] 프롬프트 선택 및 편집`에서 타임라인 분석과 최종 교정 프롬프트를
`[]` 제목 구간별로 켜고 끌 수 있습니다. 프롬프트와 휴지통을 탭으로 나누며, 구간 본문을
불러와 조금만 수정하고 버전 이력을 보거나 새 구간을 추가·삭제·복원할 수 있습니다.
프롬프트 탭의 위/아래 버튼으로 순서를 바꾸면 미리보기와 실제 전송 순서에 반영됩니다.

적용하려면 두 호출 단계 각각에서 하나 이상의 구간을 선택해야 합니다. 부분 수정은 기본
구간의 revision을 교체해 원본과 수정본이 중복 전송되지 않습니다. 저장과 적용은 별도이며,
적용 전에는 이전 선택이 유지됩니다. 후처리 코드는 별도로 점수 기준 필터와 시간·분류·표기
보정을 하므로 화면에서 해당 사실을 안내합니다. Tkinter를 사용할 수 없을 때는 콘솔에서
`t`로 프롬프트/휴지통을 전환하고 `u번호`/`d번호`로 항목을 이동할 수 있습니다.

메뉴 `[1]` 또는 `[2]`의 모델 호출 직전 전달 내용을 확인하려면 `config.json`에서 다음 값을
설정합니다. `preview`에서는 선택 항목과 프롬프트 일부가 먼저 표시되고, 그 다음 Codex 호출
상태가 출력된 뒤 모델 요청을 보냅니다.

```json
{
  "PROMPT_DEBUG_MODE": "preview",
  "PROMPT_DEBUG_LINES": 10
}
```

`off`는 기본값으로 아무 내용도 출력하지 않습니다. `summary`는 선택 구간과 전송문 길이·해시를,
`preview`는 여기에 전송문 앞 N줄과 마지막 지시를 덧붙여 보여줍니다. `full`은 미리보기와 함께
실제 프롬프트 TXT, 별도 schema JSON, 요청 정보를 `prompt_debug/`에 저장합니다. 전체 파일에는
STT·채팅 등 입력 데이터가 들어갈 수 있으므로, `full`은 로컬에서 내용을 확인하고 보관 위치를
관리할 수 있을 때 사용하세요. `PROMPT_DEBUG_LINES`는 1~200줄 범위로 설정할 수 있습니다.
schema가 전달되는 타임라인 분석과 달리 최종 교정은 별도 schema가
없다고 표시합니다. 빈 모델 설정은 `CLI default (actual model unknown)`으로 표시됩니다.

구간과 버전은 `prompts/prompt_registry.json`에 저장됩니다. 기존 v1 저장소는 앱에서
마이그레이션할 때 `prompt_registry.json.v1.bak`에 원본을 보존합니다.

메뉴 `[1]` 또는 `[2]`에서 `"PROMPT_RESEARCH_ENABLED": true`를 지정하면 실제 전송 프롬프트,
STT·채팅, 모델 원응답과 정제 결과가 `prompt_research/`에 로컬 저장됩니다. 원문이
포함되므로 기본값은 꺼져 있습니다. 설정된 모델명이 빈 값이면 실제 선택 모델을 확인할 수
없어 `CLI default`로 표시합니다.

두 연구 기록의 같은 입력을 구조적으로 비교하려면 다음을 실행합니다.

```bash
python src/code/compare_prompt_runs.py prompt_research/<run-A>.json prompt_research/<run-B>.json
```

이 도구는 동일 단계·입력 기록과 프롬프트 차이 및 출력 길이를 보여줍니다. 의미상 정확도는
사람이 정답 표본을 마련해 별도로 평가해야 합니다.

---

# 🛠️ 설치 방법

## Python 설치

* Python 3.10 이상 권장

---

## [FFmpeg 설치](https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip)

```bash
ffmpeg -version
```

PATH 등록 필요

---

## 패키지 설치

```bash
pip install -r requirements.txt
```

# 🔥 엔비디아 CUDA 환경에서 PyTorch 재설치 (GPU 가속 권장)

Faster-Whisper 및 AI 연산 속도를 제대로 활용하려면 CUDA가 활성화된 PyTorch 환경을 사용하는 것을 권장합니다.

먼저 기존 torch를 제거합니다.

```bash id="v8m31m"
pip uninstall torch torchvision torchaudio -y
```

---

## CUDA 12.1 환경 (권장)

최신 NVIDIA 드라이버 사용 시 추천

```bash id="p9m8qb"
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
```

---

## CUDA 11.8 환경

구형 환경 또는 호환성 우선 시 사용

```bash id="fsc69q"
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
```

---

# 📚 주요 의존성

```text
faster-whisper
yt-dlp
ffmpeg-python
Codex CLI (`@openai/codex`)
pydantic
browser-cookie3
torch
ctranslate2
```

---

# ▶️ 실행 방법

```bash
# 저장소 루트에서 실행
python src/code/Main.py
```

---

# ⚡ 성능 참고

| 환경      | 처리 속도 |
| ------- | ----- |
| RTX GPU | 매우 빠름 |
| CPU     | 느림    |

---

# ⚠️ 주의사항

* Codex 호출은 로그인한 ChatGPT 플랜의 사용량 제한을 따릅니다.

* 19금 VOD는 미지원 합니다.
* 치지직 댓글 제한: 5000자
* 비공식 API 기반 프로젝트
* 치지직 구조 변경 시 일부 기능이 동작하지 않을 수 있음

---

# 🕓 버전 기록

## v3.0.0

* AI 엔진 교체: Gemini API → **Codex CLI** (`codex login`으로 ChatGPT 구독 계정 로그인, API 키 불필요)
* 댓글 자동 등록 기능 제거: 타임라인은 `TL_VOD_...txt` 초안 파일로 저장되고 기본 편집기로 자동 오픈, 직접 검토 후 수동 게시
* 오디오 다운로드 3단계 폴백 구조 도입 (yt-dlp → CHZZK API → `ChzzkVideoDownloader.exe`)
* 영상 길이 조회도 yt-dlp 실패 시 CHZZK API로 자동 대체

전체 변경 내역은 [Releases](https://github.com/seoldam82/Chzzk-Timeline-Manager/releases)에서 확인할 수 있습니다.

---

# 📜 라이센스 및 면책사항

본 프로젝트는 개인 편의를 위한 비공식 자동화 도구입니다.

NAVER 및 CHZZK와 제휴 관계가 없으며, 댓글 내용·저작권·플랫폼 정책 위반 등에 대한 책임은 사용자 본인에게 있습니다.

---

