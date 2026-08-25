import requests
# import time
# import json

DATA_URL = "https://dp4p6x0xfi5o9.cloudfront.net/maimai/data.json"

def get_data():
    """곡 정보 json 에서 불러오기"""

    raw_data = requests.get(DATA_URL, timeout=10).json()
    # with open(r'C:\Users\teru\Desktop\miruku\milkbot\data.json', "r", encoding="utf-8") as f:
    #     raw_data = json.load(f)
    # print(raw_data)
    songs = raw_data["songs"]
    # categories = raw_data["categories"]
    versions = raw_data["versions"]
    # types = raw_data["types"]
    # difficulties = raw_data["difficulties"]
    # regions = raw_data["regions"]
    updateTime = raw_data["updateTime"]
    # return songs, categories, versions, types, difficulties, regions, updateTime

def search_chart(category: list | None = None, version: list | None = None, type_: list | None = None, 
                 difficulty: list | None = None, diff_min: float | None = None, diff_max: float | None = None, 
                 p2_difficulty: list | None = None, p2_diff_min: float | None = None, p2_diff_max: float | None = None, region = "intl") -> tuple[list[dict], bool]:
    """곡 정보 json 에서 검색
    예외처리 x"""

    p2 = True if (p2_difficulty or p2_diff_min or p2_diff_max) else False #채보 2개 고려 여부

    songs, _, _, _, _, _, _ = get_data()
    results = []
    for song in songs:
        if (
            (not category or song["category"] in category)
            and (not version or song["version"] in version)
        ):
            sheet_results = []
            for sheet in song["sheets"]:
                if ((not type_ or sheet["type"] in type_)
                and (not difficulty or sheet["difficulty"] in difficulty)
                and (not diff_min or sheet["internalLevelValue"] >= diff_min)
                and (not diff_max or sheet["internalLevelValue"] <= diff_max)
                and (not region or sheet["regions"].get(region, False))):
                    if not p2:
                        sheet_results.append(sheet)
                    else:
                        p2_sheet_results = []
                        for p2_sheet in song["sheets"]:
                            if ((p2_sheet["type"] == sheet["type"])
                            and (not p2_difficulty or p2_sheet["difficulty"] in p2_difficulty)
                            and (not p2_diff_min or p2_sheet["internalLevelValue"] >= p2_diff_min)
                            and (not p2_diff_max or p2_sheet["internalLevelValue"] <= p2_diff_max)):
                                p2_sheet_results.append(p2_sheet)
                        if p2_sheet_results:
                            twosheet = {
                                "p1_sheet": sheet,
                                "p2_sheet": p2_sheet_results
                            }
                            sheet_results.append(twosheet)
            if sheet_results:
                summary = {
                    "category": song["category"],
                    "title": song["title"],
                    "artist": song["artist"],
                    "bpm": song["bpm"],
                    "imageName": song["imageName"],
                    "version": song["version"],
                    "isLocked": song["isLocked"],
                    "comment": song["comment"],
                    "sheets": sheet_results
                }
                results.append(summary)
    return results, p2

if __name__ == "__main__":
    # start_time = time.time()
    songs, _, _, _, _, _, updateTime = get_data()
    # print(f"곡 정보 json 불러오기 완료. 소요 시간: {time.time() - start_time:.2f}초")
    print(f"곡 수: {len(songs)}")
    print(f"업데이트 시간: {updateTime}")
    # start_time = time.time()
    results, _ = search_chart(diff_min = 15.0, version = ["BUDDiES"])
    # print(f"검색 완료. 소요 시간: {time.time() - start_time:.2f}초")
    print(f"검색 결과 수: {len(results)}")
    print(f"대표 검색 결과: {results[0] if results else 'none'}")