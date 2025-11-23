import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus

def search_audiobookbay(query=None, page=1):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/114.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9"
    }

    # Determine the correct URL
    if query is None:
        if page == 1:
            url = "https://audiobookbay.lu"
        else:
            url = f"https://audiobookbay.lu/page/{page}/"
    else:
        encoded_query = quote_plus(query.lower())
        url = f"https://audiobookbay.lu/page/{page}/?s={encoded_query}&cat=undefined%2Cundefined"

    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        raise Exception(f"Failed to fetch results from {url}")

    soup = BeautifulSoup(response.text, "html.parser")
    posts = soup.select("div.post,div.post.re-ab")

    results = []
    for post in posts:
        title_tag = post.select_one("div.postTitle h2 a")
        if not title_tag:
            continue

        title = title_tag.text.strip()
        link = "https://audiobookbay.lu" + title_tag.get("href")

        img_tag = post.select_one("div.postContent img")
        img = img_tag.get("src") if img_tag else None

        size_tag = post.select_one("div.postContent p[style*='text-align:center;']")
        size = size_tag.text.strip().replace("\n", " ") if size_tag else None

        results.append({
            "title": title,
            "link": link,
            "image": img,
            "details": size
        })

    return results