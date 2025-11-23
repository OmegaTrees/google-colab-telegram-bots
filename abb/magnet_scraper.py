def get_magnet_data(url):
    import requests
    from bs4 import BeautifulSoup
    from urllib.parse import quote
    import textwrap

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/114.0.0.0 Safari/537.36"
        )
    }

    response = requests.get(url, headers=headers)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')

    # Title
    title_tag = soup.find('h1')
    title = title_tag.get_text(strip=True) if title_tag else 'N/A'

    # Image
    image_url = 'N/A'
    img_tag = soup.find('img', attrs={'itemprop': 'image'})
    if img_tag and img_tag.has_attr('src'):
        image_url = img_tag['src']
    else:
        for img in soup.find_all('img'):
            src = img.get('src', '')
            if 'm.media-amazon.com' in src or src.endswith(('.jpg', '.jpeg', '.png')):
                image_url = src
                break

    # Description
    desc_tag = soup.find(class_='desc')
    description = desc_tag.get_text(strip=True) if desc_tag else 'N/A'

    # Info Hash and Trackers
    info_hash = None
    trackers = []
    for row in soup.find_all('tr'):
        cols = row.find_all('td')
        if len(cols) == 2:
            key = cols[0].get_text(strip=True)
            value = cols[1].get_text(strip=True)
            if "Info Hash" in key:
                info_hash = value
            elif "Tracker" in key or value.startswith(("udp://", "http://", "https://")):
                trackers.append(value)

    # Magnet link
    magnet_link = "N/A"
    if info_hash:
        tracker_params = ''.join(f"&tr={quote(tr)}" for tr in trackers)
        magnet_link = f"magnet:?xt=urn:btih:{info_hash}&dn={quote(title)}{tracker_params}"

    return {
        "title": title,
        "image_url": image_url,
        "description": description,
        "magnet_link": magnet_link
    }

