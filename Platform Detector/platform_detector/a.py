# # from stealth_browser_controller import StealthBrowserController

# # CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

# # URL = "https://www.klook.com/"

# # browser = StealthBrowserController(
# #     browser_path=CHROME_PATH
# # )

# # try:
# #     success = browser.open(
# #         url=URL,
# #         wait_time=5,
# #         max_retries=2
# #     )

# #     print("Browser opened:", success)

# # finally:
# #     browser.close()


# import inspect
# from stealth_browser_controller import StealthBrowserController

# browser = StealthBrowserController(
#     browser_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe"
# )

# print("\n========== CLASS FILE ==========")
# print(inspect.getfile(StealthBrowserController))

# print("\n========== INSTANCE ATTRIBUTES ==========")
# print(vars(browser))

# print("\n========== POSSIBLE DRIVER ATTRIBUTES ==========")
# for attr in dir(browser):
#     if any(x in attr.lower() for x in [
#         "driver", "browser", "chrome", "page", "session", "element"
#     ]):
#         try:
#             value = getattr(browser, attr)
#             print(attr, ":", type(value))
#         except Exception:
#             pass

# print("\n========== CLASS SOURCE ==========")
# print(inspect.getsource(StealthBrowserController))

# browser.close()

# test_proxy.py
# from curl_cffi import requests

# PROXY = "http://smart-tti0q16uqyca:Zq6tUW02FqlRx84Q@proxy.smartproxy.net:3120"

# session = requests.Session(impersonate="chrome")

# # Test 1: Check your proxy IP
# resp = session.get("https://httpbin.org/ip", proxies={"https": PROXY})
# print(f"Proxy IP: {resp.json()}")

# # Test 2: Hit klook.com
# resp = session.get(
#     "https://www.klook.com/",
#     proxies={"https": PROXY},
#     headers={
#         "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
#         "Accept-Language": "en-US,en;q=0.9",
#     },
# )
# print(f"Klook status: {resp.status_code}")
# print(f"Title: {resp.text[resp.text.find('<title>')+7:resp.text.find('</title>')]}")
import requests
proxyip = "http://smart-tti0q16uqyca:Zq6tUW02FqlRx84Q@proxy.smartproxy.net:3120"
url = "https://api.ip.cc"
proxies={
    'http':proxyip,
    'https':proxyip,
}
data = requests.get(url=url,proxies=proxies)
print(data.text)