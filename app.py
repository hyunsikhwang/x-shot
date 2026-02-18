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


def extract_post_id(post_url: str) -> Optional[str]:
    parts = [part for part in post_url.rstrip("/").split("/") if part]
    if len(parts) < 2:
        return None
    post_id = parts[-1]
    if re.fullmatch(r"\d+", post_id):
        return post_id
    return None


@st.cache_resource
def ensure_playwright_browser() -> str:
    cmd = ["playwright", "install", "chromium"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"Playwright 브라우저 설치 실패: {details}")
    return "chromium-ready"


async def _capture_x_post_png_async(post_url: str, theme: str = "light") -> bytes:
    page_color = "#ffffff" if theme == "light" else "#0f1115"

    async def expand_show_more(article_locator) -> None:
        selectors = [
            "div[role='button']:has-text('Show more')",
            "span:has-text('Show more')",
            "div[role='button']:has-text('더 보기')",
            "span:has-text('더 보기')",
            "div[role='button']:has-text('더보기')",
            "span:has-text('더보기')",
        ]
        for _ in range(8):
            clicked = False
            for selector in selectors:
                targets = article_locator.locator(selector)
                count = await targets.count()
                for idx in range(min(count, 6)):
                    node = targets.nth(idx)
                    try:
                        if await node.is_visible(timeout=200):
                            await node.click(timeout=2000)
                            await asyncio.sleep(0.15)
                            clicked = True
                    except Exception:
                        continue
            if not clicked:
                break

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 2400},
            device_scale_factor=2,
            color_scheme=theme,
            locale="ko-KR",
        )
        async def bypass_document_csp(route):
            request = route.request
            if request.resource_type == "document" and "x.com/" in request.url:
                response = await route.fetch()
                headers = {
                    k: v
                    for k, v in response.headers.items()
                    if k.lower()
                    not in {"content-security-policy", "content-security-policy-report-only"}
                }
                body = await response.body()
                await route.fulfill(response=response, headers=headers, body=body)
                return
            await route.continue_()

        await context.route("**/*", bypass_document_csp)
        page = await context.new_page()

        try:
            tweet_id = extract_post_id(post_url)
            if not tweet_id:
                raise ValueError("게시물 ID를 추출할 수 없습니다.")

            await page.goto(post_url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(800)

            dismiss_selectors = [
                "button:has-text('Not now')",
                "button:has-text('나중에')",
                "button[aria-label='닫기']",
                "div[role='button'][aria-label='닫기']",
            ]
            for selector in dismiss_selectors:
                btn = page.locator(selector).first
                try:
                    if await btn.is_visible(timeout=500):
                        await btn.click(timeout=2000)
                        await page.wait_for_timeout(200)
                except Exception:
                    continue

            try:
                await page.add_style_tag(
                    content=f"""
                    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
                    html, body {{
                      background: {page_color} !important;
                    }}
                    article, article * {{
                      font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
                    }}
                    """
                )
            except Exception:
                # CSP 우회가 환경별로 동작하지 않을 때도 캡처는 계속 진행한다.
                await page.add_style_tag(
                    content=f"""
                    html, body {{
                      background: {page_color} !important;
                    }}
                    article, article * {{
                      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
                    }}
                    """
                )

            tweet = page.locator(f"article:has(a[href*='/status/{tweet_id}'])").first
            try:
                await tweet.wait_for(timeout=30000)
            except Exception:
                # fallback: 상세 페이지에서 첫 번째 article
                tweet = page.locator("article").first
                await tweet.wait_for(timeout=30000)

            await expand_show_more(tweet)
            await tweet.scroll_into_view_if_needed(timeout=3000)
            await page.wait_for_timeout(500)

            box = await tweet.bounding_box()
            if box and box.get("height", 0) > 0:
                desired_h = int(box["height"]) + 240
                adjusted_h = max(1600, min(desired_h, 14000))
                await page.set_viewport_size({"width": 1280, "height": adjusted_h})
                await page.wait_for_timeout(400)
                await tweet.scroll_into_view_if_needed(timeout=3000)

            stable = 0
            prev_h = -1

            for _ in range(36):
                cur_box = await tweet.bounding_box()
                if cur_box and cur_box.get("height", 0) > 160:
                    curr_h = int(cur_box["height"])
                    if abs(curr_h - prev_h) <= 1:
                        stable += 1
                    else:
                        stable = 0
                    prev_h = curr_h
                    if stable >= 3:
                        break
                await page.wait_for_timeout(250)

            await page.wait_for_timeout(800)
            image_bytes = await tweet.screenshot(type="png")
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
