import asyncio
import json
import re
from pathlib import Path
import logging

import aiohttp
import requests

logging.basicConfig(level=logging.INFO)


class MangaDownloader:
    base_url = 'https://mangalib.me/'

    def __init__(self, manga_url):
        if not manga_url.startswith(MangaDownloader.base_url):
            raise Exception("URL is not from mangalib.me")

        try:
            self.data = self._get_manga_data(manga_url)
        except Exception as e:
            logging.exception('Failed to get manga info. Ensure the URL is correct.')
            raise e

        self.chapters = self._parse_chapters()

    def _get_manga_data(self, manga_url):
        page = requests.get(manga_url)
        html = page.text
        data_json_str = re.findall(r'window\.__DATA__ = (.*);$', html, re.MULTILINE)
        data = json.loads(data_json_str[0])
        return data

    def _parse_chapters(self):
        base_url = self.base_url + self.data['manga']['slug']
        return [
            {
                "name": chapter['chapter_name'],
                "volume": chapter['chapter_volume'],
                "number": chapter['chapter_number'],
                "url": f"{base_url}/v{chapter['chapter_volume']}/c{chapter['chapter_number']}",
            }
            for chapter in reversed(self.data['chapters'])
        ]

    def get_chapter_pages(self, chapter_url):
        logging.debug("getting chapter pages for " + chapter_url)
        page = requests.get(chapter_url)
        html = page.text
        pages_json_str = re.findall(r'window\.__pg = (.*);$', html, re.MULTILINE)
        info_json_str = re.findall(r'window\.__info = (.*);$', html, re.MULTILINE)
        pages = json.loads(pages_json_str[0])
        info = json.loads(info_json_str[0])

        servers = list(info['servers'].values())
        # for each page, get the url for each server
        pages = [
            [
                s + '/' + info['img']['url'] + p['u']
                for s in servers
            ]
            for p in pages
        ]
        return pages

    async def _download(self, session, items, max_requests=20):
        # just download
        async def download__(url: str):
            async with session.get(url, headers={'referer': 'https://mangalib.me/'}) as response:
                response.raise_for_status()
                resp = await response.read()
            if not resp:
                raise Exception(f'Empty response')
            return resp

        # check that file doesn't exist; try to download from different servers
        async def download_(to_path: Path, urls: [str]):
            if to_path.exists():
                logging.debug(f'File {to_path} already exists. Skipping.')
                return

            to_path.parent.mkdir(parents=True, exist_ok=True)

            exceptions = []
            for url in urls:
                try:

                    logging.debug(f'Downloading {url} to {to_path}')
                    page = await download__(url)
                    with open(to_path, 'wb') as f:
                        f.write(page)
                    logging.debug(f' Downloaded {url} to {to_path}')

                    return
                except Exception as e:
                    logging.exception(e)
                    exceptions.append([url, e])
            raise Exception(f'Failed to download {to_path}: {exceptions}')

        # download all items
        await asyncio.gather(*[
            asyncio.create_task(download_(path_to, page_urls), name=path_to)
            for path_to, page_urls in items
        ])

    async def download(self, path: Path, max_requests=20):
        path = path / self.data['manga']['slug']

        async def download_chapter(chapter):
            pages = self.get_chapter_pages(chapter['url'])
            items = [
                (path / chapter['number'] / f"{i}.jpg", page_urls)
                for i, page_urls in enumerate(pages)
            ]

            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=max_requests)) as session:
                await self._download(session, items, max_requests=max_requests)

        for chapter in self.chapters:
            logging.info(f'Downloading {chapter["number"]} - {chapter["name"]}')
            await download_chapter(chapter)
            logging.info(f'Downloaded  {chapter["number"]} - {chapter["name"]}')


if __name__ == '__main__':
    md = MangaDownloader("https://mangalib.me/jojo-no-kimyou-na-bouken-part-7-steel-ball-run-solored/v24/c95?ui=7237121")
    asyncio.run(md.download(path=Path(__file__).parent))
