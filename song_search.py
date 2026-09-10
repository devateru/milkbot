import requests
import random
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
    # versions = raw_data["versions"]
    # types = raw_data["types"]
    # difficulties = raw_data["difficulties"]
    # regions = raw_data["regions"]

    updateTime = raw_data["updateTime"]

    return songs, updateTime


def search_chart(
    category: list | None = None,
    version: list | None = None,
    type_: list | None = ["dx", "std"],
    difficulty: list | None = None,
    diff_min: float | None = None,
    diff_max: float | None = None,
    p2_difficulty: list | None = None,
    p2_diff_min: float | None = None,
    p2_diff_max: float | None = None,
    region: str | None = "intl"
) -> list[dict]:
    """곡 정보 json 에서 검색
    예외처리 x"""

    # 함수 내부에서는 2P 검색 여부를 판단할 값이 여전히 필요함
    use_p2 = (
        bool(p2_difficulty)
        or p2_diff_min is not None
        or p2_diff_max is not None
    )

    songs, _ = get_data()
    results = []

    for song in songs:
        if (
            (not category or song["category"] in category)
            and (not version or song["version"] in version)
        ):
            sheet_results = []

            for sheet in song["sheets"]:
                if (
                    (not type_ or sheet["type"] in type_)
                    and (not difficulty or sheet["difficulty"] in difficulty)
                    and (diff_min is None or sheet["internalLevelValue"] >= diff_min)
                    and (diff_max is None or sheet["internalLevelValue"] <= diff_max)
                    and (not region or sheet["regions"].get(region, False))
                ):

                    # 2P 조건 없음
                    if not use_p2:
                        sheet_results.append(sheet)

                    # 2P 조건 있음
                    else:
                        p2_sheet_results = []

                        for p2_sheet in song["sheets"]:
                            if (
                                (p2_sheet["type"] == sheet["type"])
                                and (
                                    not p2_difficulty
                                    or p2_sheet["difficulty"] in p2_difficulty
                                )
                                and (
                                    p2_diff_min is None
                                    or p2_sheet["internalLevelValue"] >= p2_diff_min
                                )
                                and (
                                    p2_diff_max is None
                                    or p2_sheet["internalLevelValue"] <= p2_diff_max
                                )
                                and (
                                    not region
                                    or p2_sheet["regions"].get(region, False)
                                )
                            ):
                                p2_sheet_results.append(p2_sheet)

                        if p2_sheet_results:
                            sheet_results.append({
                                "p1_sheet": sheet,
                                "p2_sheets": p2_sheet_results
                            })

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

    # p2를 따로 반환하지 않음
    return results


def choose_chart(results):
    chart = random.choice(results)

    selected = random.choice(chart["sheets"])

    # 2P 조건으로 검색된 결과
    if "p1_sheet" in selected:
        p1_sheet = selected["p1_sheet"]
        p2_sheet = random.choice(selected["p2_sheets"])

    # 일반 1P 검색 결과
    else:
        p1_sheet = selected
        p2_sheet = None

    return chart, p1_sheet, p2_sheet


if __name__ == "__main__":

    # start_time = time.time()

    songs, updateTime = get_data()

    # print(f"곡 정보 json 불러오기 완료. 소요 시간: {time.time() - start_time:.2f}초")

    print(f"곡 수: {len(songs)}")
    print(f"업데이트 시간: {updateTime}")

    # start_time = time.time()

    results = search_chart(
        diff_min=13.0,
        version=["BUDDiES"],
        p2_diff_min=11,
        p2_diff_max=13
    )

    # print(f"검색 완료. 소요 시간: {time.time() - start_time:.2f}초")

    print(f"검색 결과 수: {len(results)}")

    if results:
        for i in range(1, 6):

            random_result, p1_chart, p2_chart = choose_chart(results)

            print(f"무작위 검색 결과 #{i}")

            if p2_chart is not None:
                diff = (
                    f"{p1_chart['internalLevelValue']} / "
                    f"2p_diff: {p2_chart['internalLevelValue']}"
                )
            else:
                diff = p1_chart["internalLevelValue"]

            print(
                f"title: {random_result['title']} / "
                f"artist: {random_result['artist']} / "
                f"diff: {diff}"
            )

            print("\n")

# import requests
# import random
# # import time
# # import json

# DATA_URL = "https://dp4p6x0xfi5o9.cloudfront.net/maimai/data.json"

# def get_data():
#     """곡 정보 json 에서 불러오기"""

#     raw_data = requests.get(DATA_URL, timeout=10).json()
#     # with open(r'C:\Users\teru\Desktop\miruku\milkbot\data.json', "r", encoding="utf-8") as f:
#     #     raw_data = json.load(f)
#     # print(raw_data)
#     songs = raw_data["songs"]
#     # categories = raw_data["categories"]
#     # versions = raw_data["versions"]
#     # types = raw_data["types"]
#     # difficulties = raw_data["difficulties"]
#     # regions = raw_data["regions"]
#     updateTime = raw_data["updateTime"]
#     return songs, updateTime # categories, versions, types, difficulties, regions, updateTime

# def search_chart(category: list | None = None, version: list | None = None, type_: list | None = ["dx", "std"], 
#                  difficulty: list | None = None, diff_min: float | None = None, diff_max: float | None = None, 
#                  p2_difficulty: list | None = None, p2_diff_min: float | None = None, p2_diff_max: float | None = None, region: str | None = "intl") -> tuple[list[dict], bool]:
#     """곡 정보 json 에서 검색
#     예외처리 x"""

#     p2 = True if (p2_difficulty or p2_diff_min or p2_diff_max) else False #채보 2개 고려 여부

#     songs, _ = get_data()
#     results = []
#     for song in songs:
#         if (
#             (not category or song["category"] in category)
#             and (not version or song["version"] in version)
#         ):
#             sheet_results = []
#             for sheet in song["sheets"]:
#                 if ((not type_ or sheet["type"] in type_)
#                 and (not difficulty or sheet["difficulty"] in difficulty)
#                 and (not diff_min or sheet["internalLevelValue"] >= diff_min)
#                 and (not diff_max or sheet["internalLevelValue"] <= diff_max)
#                 and (not region or sheet["regions"].get(region, False))):
#                     if not p2:
#                         sheet_results.append(sheet)
#                     else:
#                         p2_sheet_results = []
#                         for p2_sheet in song["sheets"]:
#                             if ((p2_sheet["type"] == sheet["type"])
#                             and (not p2_difficulty or p2_sheet["difficulty"] in p2_difficulty)
#                             and (not p2_diff_min or p2_sheet["internalLevelValue"] >= p2_diff_min)
#                             and (not p2_diff_max or p2_sheet["internalLevelValue"] <= p2_diff_max)
#                             and (not region or p2_sheet["regions"].get(region, False))):
#                                 p2_sheet_results.append(p2_sheet)
#                         if p2_sheet_results:
#                             sheet_results.append({
#                                 "p1_sheet": sheet,
#                                 "p2_sheets": p2_sheet_results
#                             })
#             if sheet_results:
#                 summary = {
#                     "category": song["category"],
#                     "title": song["title"],
#                     "artist": song["artist"],
#                     "bpm": song["bpm"],
#                     "imageName": song["imageName"],
#                     "version": song["version"],
#                     "isLocked": song["isLocked"],
#                     "comment": song["comment"],
#                     "sheets": sheet_results
#                 }
#                 results.append(summary)
#     return results, p2

# def choose_chart(results, p2):
#     chart = random.choice(results)

#     if p2:
#         pair = random.choice(chart["sheets"])

#         p1_sheet = pair["p1_sheet"]
#         p2_sheet = random.choice(pair["p2_sheets"])

#         return chart, p1_sheet, p2_sheet

#     else:
#         p1_sheet = random.choice(chart["sheets"])

#         return chart, p1_sheet, False

# if __name__ == "__main__":
#     # start_time = time.time()
#     songs, updateTime = get_data()
#     # print(f"곡 정보 json 불러오기 완료. 소요 시간: {time.time() - start_time:.2f}초")
#     print(f"곡 수: {len(songs)}")
#     print(f"업데이트 시간: {updateTime}")
#     # start_time = time.time()
#     results, p2 = search_chart(diff_min = 13.0, version = ["BUDDiES"], p2_diff_min = 11, p2_diff_max = 13)
#     # print(f"검색 완료. 소요 시간: {time.time() - start_time:.2f}초")
#     print(f"검색 결과 수: {len(results)}")
#     if results:
#         for i in range (1, 6):
#             random_result, p1_chart_index, p2_chart_index = choose_chart(results, p2)
#             print(f"무작위 검색 결과 #{i}")
#             if p2:
#                 diff = f"{random_result['sheets'][p1_chart_index]['internalLevelValue']} / 2p_diff: {random_result['p2_sheets'][p2_chart_index]['internalLevelValue']}"
#             else:
#                 diff = random_result['sheets'][p1_chart_index]['internalLevelValue']
#             print(f"title: {random_result['title']} / artist: {random_result['artist']} / diff: {diff}")
#             print("\n")