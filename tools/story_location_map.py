"""Reviewed native location labels paired with official English table entries."""
import json
from port_story_corpus import OUT, english_table

# The Japanese labels are exact source keys, not fuzzy searches.
MAPPING = """
PriorMapText:0|地球近海
PriorMapText:1|クロスゲート宙域
PriorMapText:2|クロスゲート近傍宙域
PriorMapText:3|月軌道外宙域
PriorMapText:5|地球連邦軍極東方面軍　伊豆基地
PriorMapText:6|インド　デリー近郊
PriorMapText:7|日本　札幌近郊
PriorMapText:8|日本　札幌地区近郊
PriorMapText:9|月　近海
PriorMapText:10|月　アシュアリー・クロイツェル上空
PriorMapText:11|パリ　地球連邦軍　統合参謀本部
PriorMapText:12|日本　神津島沖
PriorMapText:13|太平洋　海中
PriorMapText:14|パキスタン　カラチ地区
PriorMapText:15|インド　ヒンダン基地
PriorMapText:16|Ｌ２宙域
PriorMapText:17|地球　低軌道上
PriorMapText:18|クロスゲート監視艦隊
PriorMapText:19|Ｌ１宙域
PriorMapText:20|Ｌ１宙域付近
PriorMapText:21|月近傍宙域
PriorMapText:22|パリ　地球連邦政府　大統領府
PriorMapText:23|地球連邦軍南欧方面軍　アビアノ基地
PriorMapText:24|月地下　ガウ＝ラ・フューリア
PriorMapText:25|バラルの園　跡地
PriorMapText:26|ドイツ　アシュアリー・クロイツェル支社
PriorMapText:27|ドイツ　ベルリン地区
PriorMapText:28|モンテ・ディルーポ
PriorMapText:29|インドネシア　ジャカルタ近郊
PriorMapText:30|インド　デリー地区
PriorMapText:31|インドネシア　ジャカルタ地区
PriorMapText:32|台湾　桃園基地
PriorMapText:33|台湾　台北地区
PriorMapText:34|日本　鹿島灘
PriorMapText:35|日本　大阪・梅田地区
PriorMapText:36|日本　大阪地区近郊
PriorMapText:37|日本近海　海中
PriorMapText:38|日本　生駒山近辺
PriorMapText:39|日本近海
PriorMapText:40|日本　東京・新宿地区
PriorMapText:41|日本　伊豆付近　上空
PriorMapText:42|モガミ重工　海上プラント
PriorMapText:43|地球連邦軍　八雲基地
PriorMapText:44|日本　札幌地区西部　山中
PriorMapText:45|地球連邦軍　統合参謀本部
TalkBgText:0|ハガネ　戦隊司令公室
TalkBgText:1|ラブルパイラ　中央管制室
TalkBgText:2|ラブルパイラ　管制室
TalkBgText:3|クロスゲート監視艦隊旗艦　ストロング・アーク
TalkBgText:4|ガウ＝ラ・フューリア　内部
TalkBgText:5|ダークアイアン・キャッスル　内部
TalkBgText:7|ヒリュウ改　ブリッジ
TalkBgText:8|ガウ＝ラ・フューリア　玉座の間
TalkBgText:9|ガウ＝ラ・フューリア　牢獄
TalkBgText:10|伊豆基地　内部
TalkBgText:11|伊豆基地　ブリーフィング・ルーム
TalkBgText:12|ヒリュウ改　内部
TalkBgText:13|ハガネ　内部
TalkBgText:14|ハガネ　ブリーフィング・ルーム
TalkBgText:15|伊豆基地　地下格納庫
TalkBgText:16|伊豆基地　食堂
TalkBgText:17|伊豆基地　基地司令公室
TalkBgText:18|シウン家
TalkBgText:19|高校　校内
TalkBgText:20|札幌地区近郊
TalkBgText:21|地球連邦軍極東方面軍　伊豆基地　司令部
TalkBgText:22|シウン家　リビング
TalkBgText:23|ゼラニオ級戦闘空母　ブリッジ
TalkBgText:24|クロガネ　ブリーフィング・ルーム
TalkBgText:25|クロガネ　ブリッジ
TalkBgText:26|ガウ＝ラ・フューリア　格納庫
TalkBgText:28|クロガネ　格納庫
TalkBgText:29|クロガネ　艦内
TalkBgText:30|ガウ＝ラ・フューリア　刻旅の杜
TalkBgText:31|ヒリュウ改　食堂
TalkBgText:32|ヒリュウ改　格納庫
TalkBgText:33|ヒリュウ改　ブリーフィング・ルーム
TalkBgText:34|ラブルパイラ　内部
TalkBgText:35|ラブルパイラ内部
TalkBgText:36|ラブルパイラ　格納庫
TalkBgText:37|ヒリュウ改　戦隊司令公室
TalkBgText:38|ハガネ　ブリッジ
TalkBgText:39|ハガネ　格納庫
TalkBgText:40|ハガネ　食堂
TalkBgText:41|輸送機　内部
TalkBgText:42|大統領府　内部
TalkBgText:43|ガウ＝ラ・フューリア内部　諜士の間
TalkBgText:44|ガウ＝ラ・フューリア　独房
TalkBgText:45|ハガネ　格納庫内
TalkBgText:46|ハガネ　艦隊司令公室
TalkBgText:47|ハガネ　シャナ＝ミアの個室
TalkBgText:48|アシュアリー・クロイツェル支社
TalkBgText:49|伊豆基地　桟橋
TalkBgText:50|伊豆基地　司令公室
TalkBgText:51|伊豆基地　格納庫
TalkBgText:52|ハガネ　艦内
TalkBgText:53|ハガネ　医務室
TalkBgText:54|アビアノ基地　格納庫
TalkBgText:55|アビアノ基地　食堂
TalkBgText:56|シミュレーター・ルーム
TalkBgText:57|ハガネ　艦内個室
TalkBgText:58|アビアノ基地　内部
TalkBgText:61|ラブルパイラ　作戦会議室
TalkBgText:62|ヒリュウ改　艦内
TalkBgText:63|ヒリュウ改　艦内個室
TalkBgText:64|伊豆基地　司令室
TalkBgText:65|東京・新宿地区
TalkBgText:66|伊豆基地　司令部
TalkBgText:67|伊豆基地　中庭
TalkBgText:68|伊豆基地　特別病室
TalkBgText:69|伊豆基地　医務室
TalkBgText:70|モガミ重工　海上プラント内部
TalkBgText:72|シウン家　トーヤの部屋
TalkBgText:73|モガミ重工　試験場施設内
TalkBgText:77|ガウ＝ラ・フューリア　謁見の間
SubstitureText:0|鋼龍戦隊
SubstitureText:5|ゼラニオ級戦闘空母
SubstitureText:9|輸送機
"""


def main():
    result = {}
    for row in MAPPING.strip().splitlines():
        key, japanese = row.split("|", 1)
        table, physical = key.split(":")
        physical = int(physical)
        english = english_table("Talk/" + table)[physical].text
        assert japanese not in result and english
        result[japanese] = dict(english=english, mltd="Talk/" + table, physical_index=physical)
    result["ゼラニオ級戦闘空母　格納庫"] = dict(english="Zelanio-class Aircraft Carrier,Hangar",
        provenance="Translated native location using official ship and Hangar terminology; no exact MLTD label")
    (OUT / "location_dictionary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Prepared {len(result)} location/substitution labels")


if __name__ == "__main__":
    main()
