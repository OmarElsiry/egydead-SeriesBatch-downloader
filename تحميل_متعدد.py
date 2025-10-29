# تحميل_متعدد.py
import argparse
import json
import os
import time
from pathlib import Path
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    ElementClickInterceptedException,
    NoSuchElementException,
)

# Import from browser_utils
from browser_utils import setup_driver, remove_overlays

QUALITY_PRESETS = {
    "4k": "4K quality",
    "fullhd": "Full HD quality",
    "hd": "HD quality",
}
 
FINAL_DOWNLOAD_BUTTON_TARGETS = [
    {
        "name": "F1 container primary button",
        "locators": [
            (By.XPATH, "//*[@id='F1']/button"),
            (By.XPATH, "//div[@id='F1']//button"),
        ],
        "post_click_sleep": 2.0,
    },
    {
        "name": "Submit button variant",
        "locators": [
            (By.CSS_SELECTOR, "button.submit-btn"),
            (By.CSS_SELECTOR, "a.submit-btn"),
            (By.XPATH, "//button[contains(@class,'submit-btn')]")
        ],
        "post_click_sleep": 1.5,
    },
    {
        "name": "Fallback F1 button",
        "locators": [
            (By.CSS_SELECTOR, "#F1 button"),
            (By.XPATH, "//button[@id='F1']"),
        ],
        "post_click_sleep": 1.0,
    },
]

def wait_for_page_ready(driver, timeout: int = 20):
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
    except TimeoutException:
        pass
def wait_for_url_prefix(driver, prefix: str, timeout: int = 5) -> bool:
    try:
        WebDriverWait(driver, timeout).until(lambda d: d.current_url.startswith(prefix))
        return True
    except TimeoutException:
        return False
def wait_for_clickable(
    driver,
    locator,
    max_attempts: int = 30,
    wait_seconds: int = 1,
    pre_attempt_hook=None,
):
    last_error = TimeoutException("Element not found")
    for _ in range(max_attempts):
        if callable(pre_attempt_hook):
            pre_attempt_hook()
        try:
            return WebDriverWait(driver, wait_seconds).until(EC.element_to_be_clickable(locator))
        except TimeoutException as exc:
            last_error = exc
            continue
    raise last_error
def normalize_key(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())
def resolve_quality_label(raw_value: str) -> str:
    key = normalize_key(raw_value)
    return QUALITY_PRESETS.get(key, raw_value.strip())
def format_option_label(text: str) -> str:
    return " ".join(text.split())
def collect_quality_options(driver, video_id: str, timeout: int = 20):
    xpath = f"//a[contains(@href, '/f/{video_id}_')]"
    def _collect(drv):
        remove_overlays(drv)
        elements = drv.find_elements(By.XPATH, xpath)
        options = []
        for el in elements:
            href = el.get_attribute("href")
            if not href:
                continue
            label = format_option_label(el.text) or href
            options.append(
                {
                    "element": el,
                    "label": label,
                    "href": href,
                    "normalized": normalize_key(label),
                }
            )
        return options if options else False
    return WebDriverWait(driver, timeout).until(_collect)
def select_quality_option(options, desired_label: str, allow_prompt: bool):
    if desired_label:
        desired_variants = {
            normalize_key(desired_label),
            normalize_key(resolve_quality_label(desired_label)),
        }
        desired_variants.discard("")
        for option in options:
            if any(variant and variant in option["normalized"] for variant in desired_variants):
                print(f"Matched requested quality '{desired_label}' to option: {option['label']}")
                return option
        print(f"Could not match requested quality '{desired_label}'.")
    if allow_prompt:
        print("Available quality options:")
        for idx, option in enumerate(options, start=1):
            print(f" {idx}. {option['label']}")
        while True:
            choice = input("Select quality number (default 1): ").strip()
            if not choice:
                return options[0]
            if choice.isdigit():
                index = int(choice)
                if 1 <= index <= len(options):
                    return options[index - 1]
            print("Invalid selection. Please enter a valid number.")
    print(f"Defaulting to first quality option: {options[0]['label']}")
    return options[0]
def click_element(driver, element, expect_new_window: bool = False, wait_timeout: int = 1, attempts: int = 1):
    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        remove_overlays(driver)
        handles_before = set(driver.window_handles)
        try:
            element.click()
        except (ElementClickInterceptedException, StaleElementReferenceException):
            driver.execute_script("arguments[0].click();", element)
        if expect_new_window:
            try:
                WebDriverWait(driver, wait_timeout).until(lambda d: len(d.window_handles) > len(handles_before))
                newly_opened = [h for h in driver.window_handles if h not in handles_before]
                if newly_opened:
                    driver.switch_to.window(newly_opened[-1])
                    return True
            except TimeoutException:
                return False
        return False
    except Exception as exc:
        raise exc
def wait_for_final_download_button(driver, timeout: int = 20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        driver.switch_to.default_content()
        def _pre_attempt():
            driver.switch_to.default_content()
            remove_overlays(driver)
        for candidate in FINAL_DOWNLOAD_BUTTON_TARGETS:
            for locator in candidate["locators"]:
                try:
                    element = wait_for_clickable(
                        driver,
                        locator,
                        max_attempts=1,
                        wait_seconds=1,
                        pre_attempt_hook=_pre_attempt,
                    )
                    return element, candidate
                except TimeoutException:
                    continue
        frames = driver.find_elements(By.TAG_NAME, "iframe")
        prioritized, others = [], []
        for frame in frames:
            frame_id = (frame.get_attribute("id") or "").lower()
            frame_name = (frame.get_attribute("name") or "").lower()
            if "f1" in frame_id or "f1" in frame_name:
                prioritized.append(frame)
            else:
                others.append(frame)
        for frame in prioritized + others:
            try:
                driver.switch_to.frame(frame)
            except Exception:
                driver.switch_to.default_content()
                continue
            def _frame_hook():
                remove_overlays(driver)
            for candidate in FINAL_DOWNLOAD_BUTTON_TARGETS:
                for locator in candidate["locators"]:
                    try:
                        element = wait_for_clickable(
                            driver,
                            locator,
                            max_attempts=1,
                            wait_seconds=1,
                            pre_attempt_hook=_frame_hook,
                        )
                        return element, candidate
                    except TimeoutException:
                        continue
            driver.switch_to.default_content()
    driver.switch_to.default_content()
    raise TimeoutException("Final download button not found within the expected timeout.")
def click_final_download_button(driver):
    button_element, candidate = wait_for_final_download_button(driver)
    candidate_name = candidate.get("name", "Final download button")
    print(f"Clicking final download button '{candidate_name}'...")
    new_window_opened = click_element(
        driver,
        button_element,
        expect_new_window=True,
        wait_timeout=2,
    )
    if new_window_opened:
        wait_for_page_ready(driver, timeout=10)
    else:
        wait_for_page_ready(driver, timeout=5)
    sleep_seconds = candidate.get("post_click_sleep", 0)
    if sleep_seconds:
        time.sleep(sleep_seconds)
    driver.switch_to.default_content()
    return new_window_opened
def click_post_download_link(driver):
    target_xpath = "/html/body/main/div/section/div/div[1]/div/a"
    print("Waiting for post-download link...")
    driver.switch_to.default_content()
    remove_overlays(driver)
    try:
        link = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.XPATH, target_xpath))
        )
    except TimeoutException:
        print("Post-download link not found within timeout.")
        return False
    print("Clicking post-download link...")
    new_window_opened = click_element(driver, link, expect_new_window=True, wait_timeout=1)
    if new_window_opened:
        wait_for_page_ready(driver, timeout=10)
    else:
        wait_for_page_ready(driver, timeout=5)
    driver.switch_to.default_content()
    print(f"Post-download link URL: {driver.current_url}")
    return True
def run_automation(video_id: str, quality_label: str, allow_prompt: bool, browser: str, base_url: str, start_from_download: bool = False, download_page_url: str = None):
    driver = None
    max_retries = 3
    attempt = 0
   
    while attempt < max_retries:
        attempt += 1
        print(f"\n=== Attempt {attempt}/{max_retries} ===")
       
        try:
            if driver is None:
                driver = setup_driver(browser=browser)
           
            video_url = f"{base_url}/{video_id}"
            if not download_page_url:
                download_page_url = f"{base_url}/f/{video_id}"
            if start_from_download:
                print(f"Opening download page directly: {download_page_url}")
                driver.get(download_page_url)
                wait_for_page_ready(driver, timeout=20)
                remove_overlays(driver)
            else:
                print(f"Opening video page: {video_url}")
                driver.get(video_url)
                wait_for_page_ready(driver, timeout=20)
                remove_overlays(driver)
                try:
                    download_link = WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((
                            By.XPATH,
                            "//a[contains(@href, '/f/') and contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'download')]",
                        ))
                    )
                except TimeoutException:
                    raise RuntimeError("Could not find the Download button on the video page.")
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", download_link)
                remove_overlays(driver)
                print("Clicking the Download button...")
                opened = click_element(driver, download_link, expect_new_window=True)
                if opened:
                    wait_for_page_ready(driver, timeout=10)
                else:
                    wait_for_page_ready(driver, timeout=5)
                if not wait_for_url_prefix(driver, download_page_url, timeout=5):
                    print("Falling back to direct download page navigation...")
                    driver.get(download_page_url)
                    wait_for_page_ready(driver, timeout=20)
            print(f"On download selection page: {driver.current_url}")
            remove_overlays(driver)
            quality_options = collect_quality_options(driver, video_id)
            selected_option = select_quality_option(quality_options, quality_label, allow_prompt)
            print(f"Clicking the '{selected_option['label']}' quality link...")
            quality_opened = click_element(driver, selected_option["element"], expect_new_window=True)
            if quality_opened:
                wait_for_page_ready(driver, timeout=10)
            else:
                wait_for_page_ready(driver, timeout=5)
            if not wait_for_url_prefix(driver, selected_option["href"], timeout=5):
                print("Navigating directly to the selected quality URL...")
                driver.get(selected_option["href"])
                wait_for_page_ready(driver, timeout=20)
            remove_overlays(driver)
            click_final_download_button(driver)
            if click_post_download_link(driver):
                print("\n✓ Download completed successfully!")
                return driver.current_url
            else:
                return None
        except Exception as e:
            print(f"Error on attempt {attempt}: {str(e)}")
            if attempt < max_retries:
                print("Retrying...")
                # Restart driver
                if driver:
                    try:
                        driver.quit()
                    except Exception:
                        pass
                driver = None
            else:
                print(f"Failed after {max_retries} attempts.")
                return None
       
    if driver:
        try:
            driver.quit()
        except Exception:
            pass
    return None
def parse_args():
    parser = argparse.ArgumentParser(description="Automate video downloads via Selenium.")
    parser.add_argument("--video-id", help="Video identifier from the URL", dest="video_id")
    parser.add_argument(
        "--quality",
        help="Desired quality label (e.g. 'Full HD', 'HD', '4K'). Defaults to 'Full HD'.",
        dest="quality",
        default="Full HD",
    )
    parser.add_argument(
        "--no-prompt",
        help="Do not prompt for missing information; fail instead.",
        dest="no_prompt",
        action="store_true",
    )
    parser.add_argument(
        "--browser",
        help="Browser to use (chrome or brave). Defaults to chrome.",
        dest="browser",
        default="chrome",
        choices=["chrome", "brave"],
    )
    parser.add_argument(
        "--base-url",
        help="Base URL of the site (e.g. 'https://cavanhabg.com').",
        dest="base_url",
    )
    parser.add_argument(
        "--start-from-download",
        help="Start directly from the download page (skipping video page).",
        dest="start_from_download",
        action="store_true",
    )
    parser.add_argument(
        "--download-page-url",
        help="Direct download page URL (if starting from download page).",
        dest="download_page_url",
        default=None,
    )
    return parser.parse_args()
def main():
    args = parse_args()
    base_url = args.base_url
    if not base_url:
        if args.no_prompt:
            raise SystemExit("--base-url is required when --no-prompt is set.")
        base_url = input("Enter the base URL (e.g. https://cavanhabg.com): ").strip()
    if not base_url:
        raise SystemExit("Base URL cannot be empty.")
    video_id = args.video_id
    if not video_id:
        if args.no_prompt:
            raise SystemExit("--video-id is required when --no-prompt is set.")
        video_id = input("Enter the video ID (e.g. oy2o53wfiw82): ").strip()
    if not video_id:
        raise SystemExit("Video ID cannot be empty.")
    quality_input = args.quality or "Full HD"
    if not quality_input:
        if args.no_prompt:
            raise SystemExit("Quality must be provided when --no-prompt is set.")
        quality_input = input("Choose quality (4K / Full HD / HD): ").strip() or "Full HD"
    print(f"Using video ID '{video_id}' with quality '{quality_input}' and base URL '{base_url}'.")
    result = run_automation(video_id, quality_input, allow_prompt=not args.no_prompt, browser=args.browser, base_url=base_url, start_from_download=args.start_from_download, download_page_url=args.download_page_url)
    if result:
        print(f"Final download page URL: {result}")
    else:
        print("Failed to complete download automation.")
if __name__ == "__main__":
    main()