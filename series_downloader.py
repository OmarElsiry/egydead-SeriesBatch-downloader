import sys
import re
from pathlib import Path
import requests
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException, StaleElementReferenceException

# Import from browser_utils
from browser_utils import setup_driver, remove_overlays

# Import from the second file (assuming it's in the same directory)
from تحميل_متعدد import run_automation

def debug(message):
    print(message, file=sys.stderr)

def sanitize_folder_name(name):
    sanitized = re.sub(r'[^a-zA-Z0-9]', '_', name)
    sanitized = sanitized.strip('_')
    return sanitized if sanitized else 'downloads'

def ensure_download_directory(folder_name):
    path = Path(folder_name)
    path.mkdir(parents=True, exist_ok=True)
    return path

def extract_season_links(series_url):
    session = requests.Session()
    response = session.get(series_url)
    soup = BeautifulSoup(response.text, 'html.parser')
    items = soup.select('li.movieItem a')
    season_links = [a['href'] for a in items if '/season/' in a['href']]
    season_links = list(set(season_links))  # remove duplicates
    debug(f"Found {len(season_links)} season links")
    return season_links

def extract_episode_links(season_url):
    session = requests.Session()
    response = session.get(season_url)
    soup = BeautifulSoup(response.text, 'html.parser')
    items = soup.select('.EpsList li a')
    episode_links = [a['href'] for a in items if '/episode/' in a['href']]
    debug(f"Found {len(episode_links)} episode links for {season_url}")
    return episode_links

def get_episode_page_with_servers(episode_url):
    session = requests.Session()
    response = session.get(episode_url)
    response.raise_for_status()
    post_response = session.post(episode_url, data={'View': '1'})
    post_response.raise_for_status()
    soup = BeautifulSoup(post_response.text, 'html.parser')
    return soup

def extract_server_link(episode_url, wanted_servers):
    soup = get_episode_page_with_servers(episode_url)
    servers = soup.select('ul.donwload-servers-list li')
    print(f"Found {len(servers)} servers for episode: {episode_url}")
    link = None
    selected_server = None
    for li in servers:
        ser_name_span = li.find('span', class_='ser-name')
        if ser_name_span:
            ser_name = ser_name_span.text.strip()
            print(f"Server: {ser_name}")
            if ser_name in wanted_servers:
                a = li.find('a', class_='ser-link')
                if a:
                    link = a['href']
                    selected_server = ser_name
                    print(f"Selected server: {selected_server}, link: {link}")
                    break
    return link, selected_server

def selenium_get_final_download(server_link_url, selected_server):
    print(f"Handling server link: {server_link_url} with server {selected_server}")
    driver = setup_driver(browser="chrome")  # Use the imported setup_driver
    driver.get(server_link_url)
    wait = WebDriverWait(driver, 30)
    final_url = None
    selectors = [
        (By.CSS_SELECTOR, 'a.btn.btn-gr.videoplayer-download'),
        (By.CSS_SELECTOR, 'button.download-btn'),
        (By.XPATH, "//a[contains(@class, 'download')]"),
        (By.XPATH, "//button[contains(@class, 'download')]"),
        (By.XPATH, "//*[contains(text(), 'Download') or contains(text(), 'download')]")
    ]
    clicked = False
    for selector in selectors:
        try:
            element = wait.until(EC.element_to_be_clickable(selector))
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
            driver.execute_script("arguments[0].click();", element)
            print(f"Clicked using selector {selector}")
            clicked = True
            break
        except TimeoutException:
            print(f"Selector {selector} failed")
            continue
    if clicked:
        try:
            submit_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'a.btn-gr.submit-btn')))
            final_url = submit_btn.get_attribute('href')
            print(f"Final URL: {final_url}")
        except TimeoutException:
            print("Could not find submit button")
    driver.quit()
    return final_url

def choose_from_list(items, title):
    print(title)
    for i, item in enumerate(items):
        print(f"{i}: {item}")
    choice = input("Enter numbers separated by comma, or 'all': ").strip().lower()
    if choice == 'all':
        return list(range(len(items)))
    else:
        selected = [int(x.strip()) - 1 for x in choice.split(',') if x.strip().isdigit()]  # 0-based
        return selected

if __name__ == "__main__":
    series_url = input("Enter SERIES_URL: ").strip()
    match = re.search(r'/([^/]+)$', series_url)
    folder_name = match.group(1) if match else 'downloads'
    folder_name = sanitize_folder_name(folder_name)
    ensure_download_directory(folder_name)
    season_links = extract_season_links(series_url)
    if not season_links:
        print("No seasons found")
        sys.exit(1)
    print(f"Found {len(season_links)} seasons")
    selected_seasons = choose_from_list(season_links, "Choose seasons:")
    wanted_servers = ["تحميل متعدد"]
    for season_idx in selected_seasons:
        season_url = season_links[season_idx]
        episode_links = extract_episode_links(season_url)
        if not episode_links:
            print(f"No episodes for this season: {season_url}")
            continue
        print(f"Season: {season_url}, Episodes: {len(episode_links)}")
        if len(selected_seasons) == 1:
            num_ep_str = input("Number of episodes to download (enter for all): ").strip()
            if num_ep_str:
                num_ep = int(num_ep_str)
                episode_links = episode_links[:num_ep]
        for ep_num, episode_url in enumerate(episode_links, start=1):
            print(f"Processing episode {ep_num}/{len(episode_links)}: {episode_url}")
            server_link, selected_server = extract_server_link(episode_url, wanted_servers)
            if not server_link:
                print("No suitable server found")
                continue
            print(f"Selected server {selected_server}, link {server_link}")
            if selected_server == 'تحميل متعدد':
                # Extract base_url and video_id from server_link
                from urllib.parse import urlparse
                parsed = urlparse(server_link)
                base_url = f"{parsed.scheme}://{parsed.netloc}"
                video_id = parsed.path.strip('/')
                quality_label = "Full HD"  # Can be made configurable
                allow_prompt = False
                browser = "chrome"
                real_final_url = run_automation(video_id, quality_label, allow_prompt, browser, base_url, start_from_download=False)
                if real_final_url:
                    ep_real_download_link = real_final_url
                    print(f"Real download link: {ep_real_download_link}")
                else:
                    print("Failed to get the final link from multi download")
            else:
                final_url = selenium_get_final_download(server_link, selected_server)
                if not final_url:
                    print("Could not obtain final download link")
                    continue
                print(f"Final direct download link: {final_url}")
                ep_real_download_link = final_url
                print(f"Real download link: {ep_real_download_link}")