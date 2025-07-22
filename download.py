
import os
import time
import re
import random
import zipfile
import shutil
import math
from typing import List, Set, Optional, Tuple
from urllib.parse import quote

import ddddocr
from PIL import Image
from io import BytesIO
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.remote.webelement import WebElement
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    UnexpectedAlertPresentException,
    NoAlertPresentException,
    WebDriverException
)

# 獲取腳本所在的目錄，確保所有檔案路徑都是相對於腳本位置的
BASE_DIR = os.path.dirname(os.path.abspath(
    __file__)) if '__file__' in locals() else os.getcwd()


class BaseThesisDownloader:
    """
    臺灣博碩士論文網自動下載器 - 基礎類別 (v4 邏輯)。
    這個基礎類別包含了所有核心的爬取、解析和下載邏輯。
    """
    # ... (此基礎類別的程式碼與前一版本完全相同，此處為節省篇幅省略)
    # ... (為了保持完整性，在下面的最終程式碼區塊中會包含全部內容)

    def __init__(self,
                 keyword: str,
                 download_dir: str = "downloaded_theses",
                 log_file: str = "download_log.txt",
                 page_progress_file: str = "page_progress.txt",
                 max_downloads_per_session: int = 70,
                 items_per_page: int = 10,
                 inter_article_sleep_range: Tuple[float, float] = (10.0, 20.0),
                 inter_page_sleep_range: Tuple[float, float] = (20.0, 45.0)
                 ):
        self.base_url = "https://ndltd.ncl.edu.tw/cgi-bin/gs32/gsweb.cgi/login?o=dwebmge"
        self.keyword = keyword
        self.download_dir = os.path.join(BASE_DIR, download_dir)
        self.log_file = os.path.join(BASE_DIR, log_file)
        self.page_progress_file = os.path.join(BASE_DIR, page_progress_file)
        self.max_downloads_per_session = max_downloads_per_session
        self.items_per_page = items_per_page
        self.inter_article_sleep_range = inter_article_sleep_range
        self.inter_page_sleep_range = inter_page_sleep_range
        self.downloaded_urls, self.last_crawled_page = self._load_log()
        self.session_download_count = 0
        self.total_pages = 0
        self.driver: Optional[webdriver.Chrome] = None
        self.wait: Optional[WebDriverWait] = None
        self.main_window_handle: Optional[str] = None
        print("[-] 正在初始化 ddddocr 引擎...")
        self.ocr = ddddocr.DdddOcr(show_ad=False)
        print("[*] ddddocr 引擎初始化完成。")
        print(f"[*] 本次執行最大下載量設定為: {self.max_downloads_per_session} 篇")
        print(f"[*] 文章間延遲範圍: {self.inter_article_sleep_range} 秒")
        print(f"[*] 翻頁間延遲範圍: {self.inter_page_sleep_range} 秒")

    def _normalize_url(self, url: str) -> Optional[str]:
        if not isinstance(url, str):
            return None
        match = re.search(r'/record\?.*$', url)
        return match.group(0) if match else None

    def _setup_driver(self):
        print("[-] 設定 Selenium WebDriver...")
        os.makedirs(self.download_dir, exist_ok=True)
        print(f"[*] 所有 PDF 將會下載至: {self.download_dir}")
        chrome_options = Options()
        prefs = {
            "download.default_directory": self.download_dir, "download.prompt_for_download": False,
            "download.directory_upgrade": True, "plugins.always_open_pdf_externally": True
        }
        chrome_options.add_experimental_option("prefs", prefs)
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-popup-blocking")
        chrome_options.add_experimental_option(
            "excludeSwitches", ["enable-automation"])
        try:
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(
                service=service, options=chrome_options)
        except Exception as e:
            print(f"[錯誤] WebDriver 初始化失敗: {e}")
            raise
        self.wait = WebDriverWait(self.driver, 20)

    def _load_log(self) -> Tuple[Set[str], int]:
        urls, last_page = set(), 1
        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                urls = {self._normalize_url(line.strip()) for line in f if line.strip(
                ) and self._normalize_url(line.strip())}
            print(f"[*] 已從 {self.log_file} 載入 {len(urls)} 筆有效紀錄。")
        except FileNotFoundError:
            print(f"[*] 未找到下載紀錄檔 {self.log_file}，將會從頭開始下載。")
        try:
            with open(self.page_progress_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content.isdigit():
                    last_page = int(content)
                    print(
                        f"[*] 已從 {self.page_progress_file} 載入上次爬取進度：從第 {last_page} 頁開始。")
                else:
                    print(f"[*] {self.page_progress_file} 內容無效，將從第 1 頁開始。")
        except FileNotFoundError:
            print(f"[*] 未找到頁數進度檔 {self.page_progress_file}，將從第 1 頁開始。")
        return urls, last_page

    def _log_download(self, url: str):
        normalized_url = self._normalize_url(url)
        if not normalized_url:
            print(f"[警告] 無法正規化此 URL，將不予記錄: {url}")
            return
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(normalized_url + '\n')
        self.downloaded_urls.add(normalized_url)
        self.session_download_count += 1
        print(
            f"      - [計數] 本次執行已下載 {self.session_download_count}/{self.max_downloads_per_session} 篇。")

    def _log_progress(self, page_num: int):
        try:
            with open(self.page_progress_file, 'w', encoding='utf-8') as f:
                f.write(str(page_num))
            print(f"[*] 已記錄頁數進度：第 {page_num} 頁。")
        except Exception as e:
            print(f"[錯誤] 記錄頁數進度時發生錯誤: {e}")

    def wait_for_manual_login(self):
        print("\n[步驟 1] 等待使用者手動登入...")
        self.driver.get(self.base_url)
        print("\n" + "="*50)
        print("★★★ 請手動操作瀏覽器 ★★★")
        print("程式已開啟網站首頁，請在瀏覽器視窗中手動完成所有登入步驟。")
        print("程式將會自動偵測登入狀態，成功登入後會自動繼續...")
        print("="*50 + "\n")
        try:
            self.wait.until(EC.presence_of_element_located(
                (By.XPATH, "//div[@class='user_area']//a[text()='登出']")))
            print("[*] 偵測到「登出」按鈕，確認使用者已登入。")
        except TimeoutException:
            raise Exception("手動登入逾時（未能偵測到「登出」按鈕）。請確保您已成功登入。")

    def run_search(self):
        print("\n[步驟 2] 執行關鍵字搜尋...")
        self.driver.get(
            "https://ndltd.ncl.edu.tw/cgi-bin/gs32/gsweb.cgi/ccd=20_UgG/search?mode=basic")
        try:
            search_box = self.wait.until(
                EC.presence_of_element_located((By.ID, "ysearchinput0")))
            search_box.send_keys(self.keyword)
            search_button = self.wait.until(
                EC.element_to_be_clickable((By.ID, "gs32search")))
            search_button.click()
            print(f"[*] 已成功提交搜尋，關鍵字為: '{self.keyword}'")
            try:
                print("[-] 正在等待總筆數資訊載入...")
                summary_container = self.wait.until(EC.visibility_of_element_located(
                    (By.XPATH, "//td[@headers='start' and contains(., '檢索結果共')]")))
                match = re.search(r'檢索結果共\s*(\d+)\s*筆資料',
                                  summary_container.text)
                if match:
                    total_items = int(match.group(1))
                    self.total_pages = math.ceil(
                        total_items / self.items_per_page)
                    print(
                        f"[*] (全新方法) 成功解析總筆數: {total_items} 筆，計算出總頁數: {self.total_pages} 頁。")
                else:
                    raise NoSuchElementException("無法從摘要文字中用 RegEx 解析總筆數")
            except (NoSuchElementException, TimeoutException):
                print("[警告] 未能成功解析到明確的總筆數，將使用「下一頁」按鈕判斷結束。")
                self.total_pages = 0
            page_to_start = self.last_crawled_page
            if page_to_start > 1:
                if self.total_pages > 0 and page_to_start <= self.total_pages:
                    print(f"[*] 嘗試跳轉到上次中斷的第 {page_to_start} 頁...")
                    try:
                        jmpage_input = self.wait.until(
                            EC.visibility_of_element_located((By.ID, "jmpage")))
                        self.driver.execute_script(
                            "arguments[0].value = arguments[1];", jmpage_input, str(page_to_start))
                        jump_button = self.wait.until(
                            EC.element_to_be_clickable((By.NAME, "jumpfmt1page")))
                        old_page_element = self.driver.find_element(
                            By.TAG_NAME, 'html')
                        jump_button.click()
                        self.wait.until(EC.staleness_of(old_page_element))
                        print(f"[*] 成功跳轉到第 {page_to_start} 頁。")
                        time.sleep(random.uniform(2.0, 4.0))
                    except Exception as e:
                        print(f"[錯誤] 跳轉頁面時發生錯誤: {e}，將從第 1 頁開始爬取。")
                        self.last_crawled_page = 1
                else:
                    print(f"[*] 上次頁數 ({page_to_start}) 無效或總頁數未知，將從頭開始。")
                    self.last_crawled_page = 1
        except TimeoutException:
            print("[錯誤] 搜尋頁面元素載入逾時。")
            self.driver.save_screenshot("search_page_timeout.png")
            raise

    def _sanitize_filename(self, name: str) -> str:
        sanitized_name = re.sub(r'[\\/*?:"<>|]', "", name)
        sanitized_name = re.sub(r'[\n\t\r]', " ", sanitized_name)
        sanitized_name = re.sub(r'\s+', " ", sanitized_name).strip()
        max_len = 150
        return sanitized_name[:max_len].strip() if len(sanitized_name) > max_len else sanitized_name

    def _parse_article_links(self) -> List[Tuple[str, str]]:
        results = []
        try:
            self.wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "td.tdfmt1-content")))
            article_elements = self.driver.find_elements(
                By.CSS_SELECTOR, "td.tdfmt1-content")
            for elem in article_elements:
                try:
                    elem_text = elem.text
                    is_embargoed = "網際網路公開日期" in elem_text
                    is_ip_restricted = "校內系統及IP範圍內開放" in elem_text
                    if is_embargoed or is_ip_restricted:
                        try:
                            title_for_log = elem.find_element(
                                By.CSS_SELECTOR, "span.etd_d").text
                            reason = "論文尚未公開 (Embargo)" if is_embargoed else "論文限校內IP (IP Restricted)"
                            print(f"    - [跳過] {reason}: {title_for_log}")
                        except NoSuchElementException:
                            print("    - [跳過] 發現一篇無法立即下載的論文。")
                        continue
                    link_tag = elem.find_element(By.CSS_SELECTOR, "a.slink")
                    title_span = link_tag.find_element(
                        By.CSS_SELECTOR, "span.etd_d")
                    url = link_tag.get_attribute('href')
                    title = title_span.text
                    if url and title:
                        results.append((url, title))
                except NoSuchElementException:
                    continue
            if not results:
                print("[提示] 本頁未找到任何有效的論文連結 (a.slink)。")
        except TimeoutException:
            print("[警告] 等待論文連結載入逾時。")
        return results

    def _wait_for_download_complete(self, timeout: int = 180) -> Optional[str]:
        print("      - 自動監控下載中...", end="")
        seconds, initial_dl_files = 0, set(os.listdir(self.download_dir))
        while seconds < timeout:
            new_files = set(os.listdir(self.download_dir)) - initial_dl_files
            if new_files:
                new_file_name = new_files.pop()
                if not new_file_name.endswith('.crdownload'):
                    full_path = os.path.join(self.download_dir, new_file_name)
                    try:
                        with open(full_path, 'rb'):
                            pass
                        print(f" 下載完成: {new_file_name}")
                        return full_path
                    except IOError:
                        pass
            time.sleep(1)
            seconds += 1
            if seconds % 10 == 0:
                print(".", end="", flush=True)
        print("\n      - [錯誤] 等待下載逾時。")
        return None

    def _preprocess_captcha_image(self, image_bytes: bytes) -> bytes:
        try:
            img = Image.open(BytesIO(image_bytes)).convert(
                'L').point(lambda p: 255 if p > 128 else 0)
            buffered = BytesIO()
            img.save(buffered, format="PNG")
            return buffered.getvalue()
        except Exception as e:
            print(f"      - [警告] 驗證碼圖片預處理失敗: {e}")
            return image_bytes

    def _solve_captcha_with_ddddocr(self, captcha_element: WebElement) -> str:
        try:
            res = self.ocr.classification(
                self._preprocess_captcha_image(captcha_element.screenshot_as_png))
            res_cleaned = ''.join(filter(str.isalnum, res)).lower()
            print(f"      - ddddocr 辨識結果: '{res}' -> 清理後: '{res_cleaned}'")
            if 4 <= len(res_cleaned) <= 6:
                return res_cleaned
            return ""
        except Exception as e:
            print(f"      - [錯誤] ddddocr 處理過程中發生錯誤: {e}")
            return ""

    def _unzip_and_cleanup(self, file_path: str, new_name_base: str):
        if not file_path.lower().endswith('.zip'):
            return
        new_pdf_name, dest_pdf_path = f"{new_name_base}.pdf", os.path.join(
            self.download_dir, f"{new_name_base}.pdf")
        print(f"      - 正在解壓縮並重新命名為: {new_pdf_name}")
        try:
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                pdf_files_in_zip = [
                    name for name in zip_ref.namelist() if name.lower().endswith('.pdf')]
                if not pdf_files_in_zip:
                    print(
                        f"      - [警告] 在 {os.path.basename(file_path)} 中未找到 PDF 檔案。")
                    return
                with zip_ref.open(pdf_files_in_zip[0]) as source, open(dest_pdf_path, 'wb') as target:
                    shutil.copyfileobj(source, target)
                print("      - 解壓縮完成。")
            os.remove(file_path)
            print(f"      - 已刪除原始 .zip 檔案: {os.path.basename(file_path)}")
        except zipfile.BadZipFile:
            print(
                f"      - [錯誤] 檔案不是一個有效的 .zip 檔案: {os.path.basename(file_path)}")
        except Exception as e:
            print(f"      - [錯誤] 解壓縮或刪除檔案時發生錯誤: {e}")

    def _handle_alert_if_present(self) -> bool:
        try:
            alert = self.driver.switch_to.alert
            print(f"      - [處理中] 偵測到警告視窗: '{alert.text}'。")
            alert.accept()
            print("      - 警告視窗已關閉。")
            return True
        except NoAlertPresentException:
            return False

    def _process_article_in_new_tab(self, article_url: str, article_title: str):
        print(f"    - 正在處理: {article_title}")
        self.driver.switch_to.new_window('tab')
        self.driver.get(article_url)
        MAX_RETRIES = 3
        try:
            self.wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//a[em[text()='電子全文']]"))).click()
            self.wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//img[@alt='電子全文']/following-sibling::a[@title='電子全文']"))).click()
            time.sleep(random.uniform(1.5, 3.0))
            self.driver.switch_to.window(self.driver.window_handles[-1])
            for i in range(MAX_RETRIES):
                print(
                    f"      - 偵測到下載宣言頁面，嘗試 ddddocr (第 {i + 1}/{MAX_RETRIES} 次)...")
                try:
                    captcha_img = self.wait.until(EC.presence_of_element_located(
                        (By.XPATH, "//img[contains(@src, 'random_validation')]")))
                    captcha_text = self._solve_captcha_with_ddddocr(
                        captcha_img)
                    if not captcha_text:
                        print("      - ddddocr 未能辨識，刷新頁面後重試...")
                        self.driver.refresh()
                        time.sleep(random.uniform(2, 4))
                        continue
                    input_box = self.driver.find_element(By.ID, "validinput")
                    input_box.clear()
                    input_box.send_keys(captcha_text)
                    time.sleep(random.uniform(0.5, 1.2))
                    self.driver.find_element(
                        By.XPATH, "//input[@value='我同意']").click()
                    time.sleep(1.5)
                    if self._handle_alert_if_present():
                        print("      - 驗證碼辨識失敗，進行下一次重試...")
                        self.driver.refresh()
                        time.sleep(random.uniform(2, 4))
                        continue
                    print("      - 未偵測到警告視窗，嘗試尋找最終下載連結...")
                    self.wait.until(EC.presence_of_element_located(
                        (By.LINK_TEXT, "下載"))).click()
                    newly_downloaded_file = self._wait_for_download_complete()
                    if newly_downloaded_file:
                        self._log_download(article_url)
                        sanitized_title = self._sanitize_filename(
                            article_title)
                        if newly_downloaded_file.lower().endswith(".zip"):
                            self._unzip_and_cleanup(
                                newly_downloaded_file, sanitized_title)
                        elif newly_downloaded_file.lower().endswith(".pdf"):
                            new_pdf_path = os.path.join(
                                self.download_dir, f"{sanitized_title}.pdf")
                            print(f"      - 正在重新命名為: {sanitized_title}.pdf")
                            if os.path.exists(new_pdf_path):
                                base, ext = os.path.splitext(new_pdf_path)
                                new_pdf_path = f"{base}_{int(time.time())}{ext}"
                            os.rename(newly_downloaded_file, new_pdf_path)
                        return sanitized_title, article_title, article_url
                    else:
                        print("      - [警告] 點擊最終連結後，下載逾時。")
                        break
                except Exception as e:
                    print(
                        f"      - [警告] 在第 {i + 1} 次重試中發生預期外的錯誤: {type(e).__name__}")
                    if self._handle_alert_if_present():
                        print("      - 已處理意外彈窗，將刷新頁面重試...")
                    else:
                        print(f"      - 錯誤詳情: {str(e)[:100]}...")
                    if i < MAX_RETRIES - 1:
                        try:
                            self.driver.refresh()
                            time.sleep(random.uniform(3, 5))
                        except Exception as refresh_e:
                            print(f"      - [嚴重] 刷新頁面失敗: {refresh_e}")
                            break
                    else:
                        print("      - 已達最大重試次數，跳過此論文。")
        except TimeoutException:
            print("      - [提示] 此頁面未找到「電子全文」按鈕或連結，自動跳過。")
        except Exception as e:
            print(f"      - [嚴重錯誤] 處理此頁面時發生未知錯誤: {e}")
            self.driver.save_screenshot(f"error_page_{int(time.time())}.png")
        finally:
            if len(self.driver.window_handles) > 1:
                self.driver.close()
            self.driver.switch_to.window(self.main_window_handle)
            sleep_duration = random.uniform(*self.inter_article_sleep_range)
            print(f"    - 論文處理完畢，隨機休息 {sleep_duration:.1f} 秒...")
            time.sleep(sleep_duration)
        return None, None, None

    def run_download_process(self):
        print("\n[步驟 3] 執行下載流程...")
        if not self.main_window_handle:
            self.main_window_handle = self.driver.current_window_handle
        page_num = self.last_crawled_page
        while True:
            if self.session_download_count >= self.max_downloads_per_session:
                print(
                    f"\n[!] 已達到本次執行下載上限 ({self.max_downloads_per_session} 篇)，程式將自動停止。")
                print(f"[!] 目前進度已儲存，下次執行將從第 {page_num} 頁繼續。")
                self._log_progress(page_num)
                break
            print(f"\n--- 正在處理第 {page_num} 頁 ---")
            print(
                f"--- 本次執行進度: {self.session_download_count}/{self.max_downloads_per_session} ---\n")
            self.driver.switch_to.window(self.main_window_handle)
            try:
                self.wait.until(
                    EC.presence_of_element_located((By.ID, "tablefmt1")))
            except TimeoutException:
                print(f"[錯誤] 第 {page_num} 頁的搜尋結果表格載入逾時，爬取結束。")
                break
            article_urls_with_titles = self._parse_article_links()
            print(f"[*] 本頁找到 {len(article_urls_with_titles)} 篇可處理的論文連結。")
            for url, title in article_urls_with_titles:
                if self.session_download_count >= self.max_downloads_per_session:
                    break
                normalized_url = self._normalize_url(url)
                if not normalized_url:
                    continue
                if normalized_url in self.downloaded_urls:
                    print(f"    - [跳過] 該論文已存在於日誌中: {title}")
                    continue
                self._process_article_in_new_tab(url, title)
            self._log_progress(page_num)
            try:
                print(f"\n[-] 正在尋找「下一頁」按鈕 (目前在第 {page_num} 頁)...")
                next_button = self.wait.until(EC.presence_of_element_located(
                    (By.CSS_SELECTOR, 'input[name="gonext"][type="image"]:not([src*="_"])')))
                self.driver.execute_script(
                    "arguments[0].click();", next_button)
                page_num += 1
                sleep_duration = random.uniform(*self.inter_page_sleep_range)
                print(
                    f"[-] 翻頁成功，前往第 {page_num} 頁。為模擬真人行為，將隨機等待 {sleep_duration:.1f} 秒...")
                time.sleep(sleep_duration)
            except TimeoutException:
                print("\n[-] 未找到可點擊的「下一頁」按鈕，可能已達最後一頁。爬取結束。")
                if self.total_pages > 0 and page_num >= self.total_pages:
                    print(f"--- 已成功爬取所有 {self.total_pages} 頁論文。 ---")
                break
            except Exception as e:
                print(f"\n[錯誤] 翻頁時發生未知錯誤: {e}。爬取結束。")
                break

    def run(self):
        try:
            self._setup_driver()
            self.wait_for_manual_login()
            self.run_search()
            self.run_download_process()
        except Exception as e:
            print(f"\n[主程式發生嚴重錯誤]：{type(e).__name__} - {e}")
            if self.driver:
                self.driver.save_screenshot("fatal_error_screenshot.png")
        finally:
            self.close()
            print("\n--- 爬蟲程式執行完畢 ---\n")

    def close(self):
        if self.driver:
            print("\n[-] 關閉 Selenium 瀏覽器。")
            self.driver.quit()
            self.driver = None


class ThesisDownloaderWithReadme(BaseThesisDownloader):
    """
    增強型臺灣博碩士論文網自動下載器 (v6)。
    兼具「事後統整」與「即時記錄」兩種模式。
    1. 啟動時，掃描資料夾，將已存在的 PDF 建立基本連結。
    2. 下載時，即時記錄新下載的 PDF，並包含完整資訊。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.readme_file = os.path.join(BASE_DIR, "README.md")
        self.readme_handle = None

    def _initialize_readme(self):
        try:
            print(f"[*] 初始化 README.md 記錄檔於: {self.readme_file}")
            self.readme_handle = open(self.readme_file, 'a+', encoding='utf-8')
            self.readme_handle.seek(0)
            if not self.readme_handle.read(1):
                session_header = (
                    f"# --- Crawler Session Started: {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n"
                    f"**Keyword:** `{self.keyword}`\n\n"
                )
                self.readme_handle.write(session_header)
                self.readme_handle.flush()
            self.readme_handle.seek(0, 2)  # Move to the end for appending
        except Exception as e:
            print(f"[錯誤] 初始化 README.md 失敗: {e}")
            self.readme_handle = None

    # ==============================================================================
    # ★★★★★★★★★★★★★★★★★★★★★★★★★ 新增的函式 ★★★★★★★★★★★★★★★★★★★★★★★★★
    # ==============================================================================
    def _consolidate_existing_pdfs(self):
        """
        [事後統整] 掃描下載資料夾，將尚未被記錄的 PDF 檔案以基本格式加入 README.md。
        """
        print("\n[統整模式] 正在檢查已存在的 PDF 檔案...")
        if not self.readme_handle:
            print("[警告] README 控制代碼未初始化，跳過統整。")
            return
        if not os.path.isdir(self.download_dir):
            print(f"[*] 下載資料夾 '{self.download_dir}' 不存在，無需統整。")
            return

        # 1. 讀取 README 中已記錄的檔名，避免重複加入
        self.readme_handle.seek(0)
        logged_pdfs = set(re.findall(
            r"\[(.*?.pdf)\]", self.readme_handle.read()))

        self.readme_handle.seek(0, 2)  # 讀取完畢後，將指標移回檔案末尾以供後續附加
        print(f"[*] README 中已記錄 {len(logged_pdfs)} 個檔案。")

        # 2. 獲取資料夾中實際存在的所有 PDF 檔名
        try:
            existing_pdfs = {f for f in os.listdir(
                self.download_dir) if f.lower().endswith('.pdf')}
        except Exception as e:
            print(f"[錯誤] 無法讀取下載資料夾 '{self.download_dir}': {e}")
            return

        # 3. 找出那些存在於資料夾、但未被記錄在 README 的檔案
        pdfs_to_add = sorted(list(existing_pdfs - logged_pdfs))

        if not pdfs_to_add:
            print("[*] 無需統整，所有已存在的 PDF 都已被記錄。")
            return

        print(f"[*] 發現 {len(pdfs_to_add)} 個尚未記錄的 PDF，現在開始寫入 README...")

        # 4. 將新發現的檔案寫入 README
        try:
            self.readme_handle.write("\n## --- 本次啟動時發現的已存在檔案 ---\n\n")
            for pdf_filename in pdfs_to_add:
                encoded_filename = quote(pdf_filename)
                pdf_relative_url = f"./{os.path.basename(self.download_dir)}/{encoded_filename}"
                # 採用精簡格式，因為沒有來源網址等詳細資訊
                readme_entry = f"* [{pdf_filename}]({pdf_relative_url}) - `(已存在於資料夾中的檔案)`\n"
                self.readme_handle.write(readme_entry)

            self.readme_handle.write("\n---\n")
            self.readme_handle.flush()
            print(f"[*] 統整完成，已將 {len(pdfs_to_add)} 個檔案連結加入 README.md。")
        except Exception as e:
            print(f"[錯誤] 寫入統整資訊到 README 時發生錯誤: {e}")

    def _log_readme_entry(self, sanitized_title: str, original_title: str, article_url: str):
        """
        [即時記錄] 將一筆成功的下載紀錄以 Markdown 格式寫入 README.md。
        """
        if self.readme_handle:
            try:
                pdf_filename = f"{sanitized_title}.pdf"
                encoded_filename = quote(pdf_filename)
                pdf_relative_url = f"./{os.path.basename(self.download_dir)}/{encoded_filename}"
                readme_entry = (
                    f"* [{pdf_filename}]({pdf_relative_url}) - {original_title} "
                    f"([Source]({article_url}))\n"
                )
                self.readme_handle.write(readme_entry)
                self.readme_handle.flush()
            except Exception as e:
                print(f"      - [警告] 寫入 README.md 失敗: {e}")

    def _setup_driver(self):
        super()._setup_driver()
        self._initialize_readme()

    # ==============================================================================
    # ★★★★★★★★★★★★★★★★★★★★★★★★★ 修改的函式 ★★★★★★★★★★★★★★★★★★★★★★★★★
    # ==============================================================================
    def run(self):
        """
        覆寫後的執行流程：
        1. 執行基礎設定 (setup)
        2. (新功能) 統整已存在的 PDF 檔案
        3. 執行完整的下載流程 (登入、搜尋、下載)
        """
        try:
            # 基礎設定，會同時初始化 README.md 控制代碼
            self._setup_driver()

            # 執行「事後統整」
            self._consolidate_existing_pdfs()

            # 執行「即時記錄」流程
            self.wait_for_manual_login()
            self.run_search()
            self.run_download_process()

        except Exception as e:
            print(f"\n[主程式發生嚴重錯誤]：{type(e).__name__} - {e}")
            if self.driver:
                self.driver.save_screenshot("fatal_error_screenshot.png")
        finally:
            self.close()
            print("\n--- 爬蟲程式執行完畢 ---\n")

    def close(self):
        if self.readme_handle:
            print("[-] 正在關閉 README.md 檔案...")
            self.readme_handle.close()
        super().close()


if __name__ == "__main__":
    SEARCH_KEYWORD = "台股"
    DOWNLOAD_LIMIT = 1000
    LONG_ARTICLE_DELAY = (15.0, 30.0)
    LONG_PAGE_DELAY = (30.0, 60.0)

    downloader = ThesisDownloaderWithReadme(
        keyword=SEARCH_KEYWORD,
        max_downloads_per_session=DOWNLOAD_LIMIT,
        inter_article_sleep_range=LONG_ARTICLE_DELAY,
        inter_page_sleep_range=LONG_PAGE_DELAY
    )
    downloader.run()


'''
python download.py

'''
