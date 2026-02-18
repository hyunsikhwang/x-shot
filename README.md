# x-shot

Playwright + Streamlit 기반의 **X(Twitter) 게시물 스크린샷 생성기**입니다.

## 기능

- `x.com` / `twitter.com` 게시물 URL 입력
- URL 정규화 후 임베드 기반으로 안정 렌더링
- 라이트 카드 스타일 PNG 캡처
- 미리보기 + 다운로드 버튼 제공

## 지원 URL 예시

- `https://x.com/jack/status/20`
- `https://twitter.com/jack/status/20?s=20`
- `https://mobile.twitter.com/jack/status/20`

## 실행

```bash
pip install -r requirements.txt
playwright install chromium
streamlit run app.py
```

## Streamlit Cloud 배포

- `requirements.txt` 사용
- `packages.txt`로 Chromium 의존 패키지 설치
- 앱 시작 시 `playwright install chromium`를 1회 실행(캐시)

## 제한 사항

- 공개 게시물만 지원합니다.
- 로그인 필요 게시물, 민감 콘텐츠, 삭제된 게시물은 실패할 수 있습니다.
- 스레드 전체가 아닌 단일 게시물 렌더를 기준으로 캡처합니다.
