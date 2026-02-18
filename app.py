import asyncio
import re
import subprocess
from typing import Optional
from urllib.parse import urlparse

import nest_asyncio
import streamlit as st
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

nest_asyncio.apply()

ALLOWED_HOSTS = {
    "x.com",
    "www.x.com",
    "twitter.com",
    "www.twitter.com",
    "mobile.twitter.com",
}


def normalize_x_post_url(url: str) -> Optional[str]:
    if not url:
        return None

    candidate = url.strip()
    if not candidate:
        return None

    if not re.match(r"^https?://", candidate, flags=re.IGNORECASE):
        candidate = f"https://{candidate}"

    parsed = urlparse(candidate)
    host = (parsed.netloc or "").lower()
    if host not in ALLOWED_HOSTS:
        return None

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 3:
        return None

    username = parts[0]
    marker = parts[1].lower()
    post_id = parts[2]

    if marker != "status":
        return None

    if not re.fullmatch(r"\d+", post_id):
        return None

    return f"https://x.com/{username}/status/{post_id}"


@st.cache_resource
def ensure_playwright_browser() -> str:
    cmd = ["playwright", "install", "chromium"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"Playwright 브라우저 설치 실패: {details}")
    return "chromium-ready"


async def _capture_x_post_png_async(post_url: str, theme: str = "light") -> bytes:
    bg_color = "#f3f5f7" if theme == "light" else "#0f1115"
    page_color = "#f3f5f7" if theme == "light" else "#0f1115"

    html = f"""
<!doctype html>
<html lang="ko">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <style>
      html, body {{
        margin: 0;
        padding: 0;
        background: {page_color};
      }}
      #capture-card {{
        width: 860px;
        margin: 36px auto;
        padding: 28px;
        border-radius: 20px;
        background: {bg_color};
        box-sizing: border-box;
      }}
      #tweet-wrap {{
        width: 100%;
      }}
      .hint {{
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        color: #6b7280;
        font-size: 13px;
        margin-top: 10px;
      }}
    </style>
    <script async src="https://platform.twitter.com/widgets.js" charset="utf-8"></script>
  </head>
  <body>
    <div id="capture-card">
      <blockquote
        id="tweet-wrap"
        class="twitter-tweet"
        data-theme="{theme}"
        data-dnt="true"
        data-conversation="none"
        data-align="center"
      >
        <a href="{post_url}"></a>
      </blockquote>
      <div class="hint">Generated with x-shot</div>
    </div>
  </body>
</html>
"""

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        context = await browser.new_context(
            viewport={"width": 1200, "height": 2400},
            device_scale_factor=2,
            color_scheme=theme,
        )
        page = await context.new_page()

        try:
            await page.set_content(html, wait_until="domcontentloaded")
            await page.wait_for_selector("#tweet-wrap iframe", timeout=20000)

            iframe = page.locator("#tweet-wrap iframe").first
            stable = 0
            prev_h = -1

            for _ in range(24):
                box = await iframe.bounding_box()
                if box and box.get("height", 0) > 160:
                    curr_h = int(box["height"])
                    if abs(curr_h - prev_h) <= 1:
                        stable += 1
                    else:
                        stable = 0
                    prev_h = curr_h
                    if stable >= 3:
                        break
                await page.wait_for_timeout(250)

            await page.wait_for_timeout(500)
            image_bytes = await page.locator("#capture-card").screenshot(type="png")
            return image_bytes
        finally:
            await browser.close()


def capture_x_post_png(post_url: str, theme: str = "light") -> bytes:
    return asyncio.run(_capture_x_post_png_async(post_url=post_url, theme=theme))


st.set_page_config(page_title="X Post Screenshot", page_icon="📸", layout="centered")
st.title("📸 X Post Screenshot")
st.caption("x.com 게시물 URL을 입력하면 깔끔한 PNG 스크린샷을 생성합니다.")

try:
    ensure_playwright_browser()
except Exception as exc:
    st.error(f"브라우저 준비 중 오류가 발생했습니다.\n\n{exc}")
    st.stop()

post_url_input = st.text_input(
    "X 게시물 URL",
    placeholder="https://x.com/<user>/status/<post_id>",
)

if st.button("스크린샷 생성", use_container_width=True):
    normalized = normalize_x_post_url(post_url_input)
    if not normalized:
        st.error("올바른 X 게시물 URL이 아닙니다. status URL을 입력해 주세요.")
    else:
        with st.spinner("게시물을 렌더링하고 이미지를 생성 중입니다..."):
            try:
                image = capture_x_post_png(normalized, theme="light")
                st.success("스크린샷 생성 완료")
                st.image(image, caption=normalized, use_container_width=True)
                post_id = normalized.rstrip("/").split("/")[-1]
                st.download_button(
                    label="PNG 다운로드",
                    data=image,
                    file_name=f"x-post-{post_id}.png",
                    mime="image/png",
                    use_container_width=True,
                )
            except PlaywrightTimeoutError:
                st.error("렌더링 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.")
            except Exception as exc:
                st.error(f"스크린샷 생성 중 오류가 발생했습니다: {exc}")

st.markdown("---")
st.markdown(
    "- 공개 게시물만 지원합니다.\n"
    "- 로그인 필요/민감 콘텐츠/삭제된 게시물은 캡처가 실패할 수 있습니다."
)
