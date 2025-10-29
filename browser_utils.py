# browser_utils.py
import argparse
import json
import os
import time

from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    ElementClickInterceptedException,
    NoSuchElementException,
)
from webdriver_manager.chrome import ChromeDriverManager

BLOCKED_URL_PATTERNS = [
    "*://*/*.jpg",
    "*://*/*.jpeg",
    "*://*/*.png",
    "*://*/*.gif",
    "*://*/*.bmp",
    "*://*/*.svg",
    "*://*/*.webp",
    "*://*.doubleclick.net/*",
    "*://*.googlesyndication.com/*",
    "*://*.googletagservices.com/*",
    "*://*.googletagmanager.com/*",
    "*://*.adnxs.com/*",
    "*://*.taboola.com/*",
    "*://*.outbrain.com/*",
    "*://*.zedo.com/*",
    "*://*.revcontent.com/*",
    "*://*.adsafeprotected.com/*",
    "*://*.moatads.com/*",
]

def locate_brave_binary() -> str | None:
    candidates = []
    program_files = os.environ.get("PROGRAMFILES")
    if program_files:
        candidates.append(os.path.join(program_files, "BraveSoftware", "Brave-Browser", "Application", "brave.exe"))

    program_files_x86 = os.environ.get("ProgramFiles(x86)")
    if program_files_x86:
        candidates.append(os.path.join(program_files_x86, "BraveSoftware", "Brave-Browser", "Application", "brave.exe"))

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(os.path.join(local_app_data, "BraveSoftware", "Brave-Browser", "Application", "brave.exe"))

    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def locate_brave_user_data_dir() -> Path | None:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None

    candidate = Path(local_app_data) / "BraveSoftware" / "Brave-Browser" / "User Data"
    return candidate if candidate.exists() else None


def ensure_brave_shields_aggressive(preferences_path: Path) -> None:
    try:
        with preferences_path.open("r", encoding="utf-8") as fp:
            prefs = json.load(fp)
    except FileNotFoundError:
        print(f"Brave preferences file not found at: {preferences_path}")
        return
    except json.JSONDecodeError:
        print(f"Brave preferences file is not valid JSON: {preferences_path}")
        return

    shields = prefs.setdefault("brave", {}).setdefault("shields", {})
    current_mode = shields.get("adblock_mode")
    if current_mode == 2:
        return

    shields["adblock_mode"] = 2

    try:
        with preferences_path.open("w", encoding="utf-8") as fp:
            json.dump(prefs, fp, indent=2)
        print("Brave Shields changed to Aggressive")
    except OSError as exc:
        print(f"Unable to write Brave preferences: {exc}")


def setup_driver(browser: str = "brave"):
    # Configure Chrome options
    chrome_options = Options()
    chrome_options.add_argument("--start-maximized")  # Start with maximized window
    chrome_options.add_argument("--remote-debugging-port=9222")  # Enable remote debugging
    chrome_options.add_argument("--no-first-run")
    chrome_options.add_argument("--no-default-browser-check")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--blink-settings=imagesEnabled=false")
    # Auto-download without prompts, to default downloads dir
    prefs = {
        "download.default_directory": os.path.join(os.getcwd(), "downloads"),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
        "profile.default_content_setting_values.popups": 2,  # Block popups
        "profile.managed_default_content_settings.popups": 2,
        "profile.managed_default_content_settings.images": 2,
        "profile.default_content_setting_values.notifications": 2,
        "profile.managed_default_content_settings.notifications": 2,
        "profile.default_content_setting_values.sound": 2,
    }
    chrome_options.add_experimental_option("prefs", prefs)

    browser_normalized = browser.lower()
    if browser_normalized == "brave":
        brave_binary = locate_brave_binary()
        if not brave_binary:
            print("Brave not found, falling back to Chrome.")
            browser_normalized = "chrome"
        else:
            user_data_dir = locate_brave_user_data_dir()
            if not user_data_dir:
                raise RuntimeError("Could not locate Brave user data directory.")
            
            preferences_path = user_data_dir / "Default" / "Preferences"
            ensure_brave_shields_aggressive(preferences_path)

            chrome_options.binary_location = brave_binary
            chrome_options.add_argument("--disable-background-networking")
            chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
            chrome_options.add_argument("--profile-directory=Default")

    if browser_normalized == "chrome":
        pass  # Use default Chrome

    # Initialize the WebDriver
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    apply_driver_hardening(driver)
    return driver


def apply_driver_hardening(driver):
    """Inject protections to block popups, images, and ad networks."""
    popup_blocking_script = """
        (() => {
            const noop = () => null;
            const blockTargets = (root = document) => {
                root.addEventListener('click', (event) => {
                    let el = event.target;
                    while (el && el !== document.body) {
                        if (el.tagName === 'A' && el.target === '_blank') {
                            el.removeAttribute('target');
                        }
                        el = el.parentElement;
                    }
                }, true);
            };

            const lockWindowApis = () => {
                try {
                    Object.defineProperty(window, 'open', { value: noop, writable: false });
                } catch (_) {
                    window.open = noop;
                }
                window.alert = noop;
                window.confirm = () => false;
                window.prompt = noop;
                window.print = () => {};
            };

            blockTargets(document);
            lockWindowApis();
        })();
    """

    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": popup_blocking_script})
        driver.execute_script(popup_blocking_script)
    except Exception as exc:  # pylint: disable=broad-except
        print(f"Unable to inject popup blocking script: {exc}")

    try:
        driver.execute_cdp_cmd("Network.enable", {})
        driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": BLOCKED_URL_PATTERNS})
    except Exception as exc:  # pylint: disable=broad-except
        print(f"Unable to configure network blocking: {exc}")


def remove_overlays_and_block_popups(driver):
    """Aggressively remove ads, overlays, and block popups"""
    driver.execute_script(
        """
        // Remove ads, overlays, etc.
        const candidates = Array.from(document.querySelectorAll('*'));
        candidates.forEach((el) => {
            try {
                const styles = window.getComputedStyle(el);
                const z = parseInt(styles.zIndex || '0', 10);
                const hasOverlayId = el.id && ['adbd', 'preloader', 'modal', 'popup', 'ad', 'banner', 'overlay'].some(id => el.id.toLowerCase().includes(id));
                const isFullscreen = styles.position === 'fixed' && (styles.width === '100%' || styles.height === '100%');
                const isLargeOverlay = styles.position === 'fixed' && parseInt(styles.width || '0') > 300 && parseInt(styles.height || '0') > 300;
                const isAdIframe = el.tagName === 'IFRAME' && el.src && (el.src.includes('ads') || el.src.includes('doubleclick') || el.src.includes('googlesyndication'));
                
                if (z > 500 || hasOverlayId || isFullscreen || isLargeOverlay || isAdIframe) {
                    el.remove();
                }
            } catch (e) {}
        });
        
        // Remove modals and ad containers
        document.querySelectorAll('[role="dialog"], .modal, .popup, .overlay, .ad-container').forEach(el => el.remove());
        
        // Remove ad scripts
        document.querySelectorAll('script[src*="ads"], script[src*="popup"], script[src*="banner"]').forEach(el => el.remove());
        
        // Block popups and new windows
        window.open = function() { return null; };
        window.alert = function() {};
        window.confirm = function() { return false; };
        window.prompt = function() { return null; };
        
        // Enable scrolling
        document.body.style.overflow = 'auto';
        """
    )

def remove_overlays(driver):
    """Aggressively remove all overlays, ads, and popups"""
    driver.execute_script(
        """
        // Remove all high z-index elements (ads, popups)
        const candidates = Array.from(document.querySelectorAll('*'));
        candidates.forEach((el) => {
            try {
                const styles = window.getComputedStyle(el);
                const z = parseInt(styles.zIndex || '0', 10);
                const hasOverlayId = el.id && ['adbd', 'preloader', 'modal', 'popup', 'ad'].some(id => el.id.toLowerCase().includes(id));
                const isFullscreen = styles.position === 'fixed' && (styles.width === '100%' || styles.height === '100%');
                const isLargeOverlay = styles.position === 'fixed' && parseInt(styles.width || '0') > 300 && parseInt(styles.height || '0') > 300;
                
                // Remove if it's likely an ad/overlay
                if (z > 1000 || hasOverlayId || isFullscreen || isLargeOverlay) {
                    el.remove();
                }
            } catch (e) {}
        });
        
        // Close any visible modals
        document.querySelectorAll('[role="dialog"], .modal, .popup').forEach(el => el.remove());
        
        // Re-enable body scrolling
        document.body.style.overflow = 'auto';
        """
    )

if __name__ == "__main__":
    driver = setup_driver(browser="brave")  # Prefer Brave for built-in ad blocking
    # Open a blank page or your desired start page
    driver.get("about:blank")
    # Apply cleanup (though blank page has nothing)
    remove_overlays_and_block_popups(driver)
    
    print("Browser launched with no ads, popups, or new windows. Press Enter to quit...")
    input()
    driver.quit()