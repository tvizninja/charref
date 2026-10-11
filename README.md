# CharRef

CharRef は、Unicode・JIS・日本語向けレガシー文字コード・各種文字集合を横断して参照するための、offline-first な single-HTML Web アプリです。

最終成果物は `dist/charref.html` です。Chrome で `file://` から直接開け、通常利用ではサーバーを必要としません。GitHub Pages では同じファイルを `index.html` として公開できます。

## 現在のデータ基準

- Unicode / UCD: **Unicode 18.0.0 official data**
- Unicode Emoji: **Emoji 18.0 official sequence data**
- Unicode code point rows: UCD range 展開を含む 312,389 rows
- Unicode 17.0 追加: 4,803 code points
- Unicode 18.0 追加: 13,007 code points
- Unihan 18.0 `kJIS0213`: 補助 cross-check property として収録
- JIS: X 0201 / X 0208 / X 0212:1990 / X 0213:2000 / X 0213:2004 と歴史版・改定差
- CP932 / Shift_JIS / EUC-JP / ISO-2022-JP と 2004 系差分
- ARIB STD-B24 固定文字・JIS 互換文字の構造化データ（DRCS は対象外）
- 学校教育: 小学校学年別漢字、常用漢字、中学校で新たに学ぶ常用漢字
- 日本漢字能力検定: 公式級別漢字表が公開されている 10級〜2級

## 主な機能

### 検索

以下を入口として文字・コード位置・sequence を検索できます。

- 実文字
- `U+XXXX`
- 16進コードポイント
- CP932 等のバイト列
- JIS の面・区・点
- Unicode name
- Collection 名
- Unicode sequence / Emoji sequence

曖昧な入力は一意に決め打ちせず、候補を表示します。複数 code point の文字列は sequence / string として解析します。

### 文字詳細

Unicode code point には以下を表示します。

- Name
- Unicode Age
- Block / Script
- General Category
- East Asian Width
- Canonical Combining Class
- Bidi Class
- Decomposition / normalization 関連情報
- Unicode binary properties
- JIS / CP932 / legacy encoding mapping
- Collection / Issue / relation
- IVS / variation sequence（該当する場合）

未割当 code point、noncharacter、surrogate、Private Use も区別して扱います。未割当等を偽の「文字」として DB に登録しません。

### Encoding 表示

Unicode 系は次の順です。

1. UTF-32
2. UTF-16BE
3. UTF-16LE
4. UTF-8

UTF-32 の code unit 値には Unicode Utilities の character page への外部リンクを付けています。外部リンクを開く場合のみネットワークが必要です。

legacy encoding は主に次を扱います。

- CP932
- Shift_JIS
- EUC-JP
- ISO-2022-JP
- Shift_JIS-2004
- EUC-JIS-2004
- ISO-2022-JP-2004

2004 系は、非 2004 系と結果が異なる場合を中心に表示します。JIS の規格上のコード位置は encoding byte 列とは別概念として表示します。

## Collection

Collection は UI 上の共通ナビゲーション単位です。内部では Unicode code point、Unicode sequence、JIS/code position 等を区別したまま保持します。

主な階層は以下です。

- Unicode
  - Blocks
  - Scripts
  - Named Sequences
  - Emoji 18.0 sequences
  - Unicode 改定差分（7.0〜18.0、表示版間の累積差分）
- JIS
  - JIS X 0201
  - JIS C 6226:1978（78JIS）
  - JIS C 6226:1983（83JIS）
  - JIS X 0208:1990（90JIS）
  - JIS X 0208
  - JIS X 0212:1990
  - JIS X 0213:2000
  - JIS X 0213:2004
  - JIS 改定差
- PC / ネット
  - CP932 repertoire / vendor extension / EUDC / decode alias 等
- 互換・幅
  - Fullwidth / Halfwidth compatibility variants
- 放送
  - ARIB STD-B24
- 教育・資格
  - 小学校学年別漢字
  - 常用漢字 2,136字
  - 中学校で新たに学ぶ常用漢字 1,110字
  - 漢検 10級〜2級
- 文字コード問題
  - SJIS trail-byte 問題
  - wave dash 系
  - CP932 / JIS X 0213 異位置等
- デバッグ
  - 構造試験

「デバッグ / 構造試験」は regression fixture の確認用です。意味のある全件集合は通常 Collection に置き、代表例だけの fixture はここへまとめています。

## Emoji 18.0

Unicode 18.0 の次の公式データを使用します。

- `emoji-sequences.txt`
- `emoji-zwj-sequences.txt`
- `emoji-test.txt`

現在の Collection は以下を含みます。

- RGI Emoji: 3,972
- Basic Emoji: 1,409
- Keycap: 12
- Flag: 259
- Tag: 3
- Modifier: 675
- ZWJ: 1,614

`emoji-test.txt` の CLDR order を RGI Emoji の表示順に利用します。

## JIS の扱い

JIS は「文字集合 / 規格上のコード位置」と「具体的な encoding」を分離します。

代表的な件数:

- JIS X 0208: 6,879位置
  - 非漢字 524
  - 第1水準 2,965
  - 第2水準 3,390
- JIS X 0212:1990: 6,067位置
  - 補助漢字 5,801
  - 非漢字 266
- JIS X 0213:2000: 11,223位置
- JIS X 0213:2004: 11,233位置
  - 第3水準 1,259
  - 第4水準 2,436

JIS Collection では原則として JIS code position を第一級の識別子として保持し、Unicode mapping が1対1でないケースを潰しません。

歴史版 78JIS / 83JIS / 90JIS も単体 Collection として保持し、改定による追加・符号位置入替・字形差は `JIS 改定差` に分けます。

## CP932 / EUDC

CP932 は canonical encode と decode alias を分けて保持します。同一 Unicode 文字に複数 CP932 code position が decode される場合も統合しません。

CP932 EUDC は `F040-F9FC` を対象とし、Windows 互換変換で Unicode PUA `U+E000-U+E757` と対応する関係を保持します。PUA は標準化された文字意味・字形を持たないため、この対応を文字の意味的同一性とは扱いません。

## ARIB STD-B24

ARIB は次を区別します。

- STD-B24 として符号化可能な範囲
- 受信機実装で共通に期待する範囲
- JIS 第3・第4水準（任意実装）
- ARIB 固定追加漢字 / 追加記号

DRCS は対象外です。

「規格上符号化可能」と「すべての受信機で実装必須」を同一視しません。

## 教育・資格

### 学校教育

- 小学校: MEXT 学年別漢字配当表、計1,026字
- 常用漢字: 2,136字
- 中学校: 常用漢字から小学校配当を除いた 1,110字

中学校の1,110字は固定の学年別配当ではありません。「中学校で新たに読む対象となる常用漢字」の集合として扱います。

### 漢検

公益財団法人 日本漢字能力検定協会が級別漢字表として公開している **10級〜2級** を収録します。準1級・1級は、同じ形式の完全な公式機械可読リストを採用できるまで対象外です。

## URL state

CharRef が使用する query parameters:

- `cp=FA11` — code point
- `seq=...` — Unicode sequence
- `pos=...` — code position
- `set=...` — Collection
- `view=grid|table` — 一覧表示
- `webfont=Noto+Sans+JP` — 外部 WebFont 比較（任意）

CharRef が認識しない query parameter は URL state 更新時にも保持します。

### WebFont

既定では外部フォントを読み込まず、offline-first を維持します。

現在の許可値:

- `?webfont=Noto+Sans+JP`
- `?webfont=Noto+Serif+JP`

指定時のみ Google Fonts を読み込み、font comparison 欄に追加します。アプリ全体の UI font は置換しません。

これは font analyzer ではありません。実フォントへの収録有無、IVS support、fallback の発生を CharRef が断定することはありません。

## Source policy

優先順位は原則として次のとおりです。

1. 規格団体・公的機関の公式データ
2. 公式資料に対応する機械可読データ
3. Unicode / Unihan 等の独立 cross-check
4. 実装 codec / runtime table を implementation cross-check

テストベクターを mapping の正本にはしません。差異がある場合は source を潰して1値へ統合せず、mapping direction / kind / priority / provenance を保持します。

`Unihan kJIS0213` は補助 cross-check であり、JIS X 0213 の normative repertoire / code position の正本には使用しません。

## ビルド

Python 3 を使用します。

### 通常の official build

ネットワーク接続可能な環境では:

```bash
python scripts/build_release.py --fetch --version v2.5
```

ローカルに official data が既にある場合:

```bash
python scripts/verify_ucd18.py --ucd-dir data/raw/unicode --manifest data/raw/manifest.json --unihan-zip data/raw/unicode/Unihan.zip
python scripts/build_ucd_db.py --ucd-dir data/raw/unicode --unicode-version 18.0.0 --dataset-kind official --unihan-zip data/raw/unicode/Unihan.zip
python scripts/validate_db.py
python scripts/export_web.py
python scripts/validate_web.py
python scripts/build_html.py
```

最終成果物は `dist/charref.html` です。

### 生成物サイズの目安

- SQLite: 約149 MB
- 展開前 `webdata.json`: 約230 MB
- single HTML: 約14 MB

SQLite と `webdata.json` は Git 管理対象外とします。GitHub Pages には single HTML のみを公開します。

## テスト

主な regression / audit:

- core regression vectors
- representative code points × codecs completeness audit
- structural vectors
- Unicode 18.0 source verification
- JIS repertoire / level / revision counts
- CP932 vendor range / alias / EUDC invariants
- Emoji sequence counts
- 教育 Collection counts
- DB → Web export information-loss checks

## Git / GitHub Pages

`.gitignore` は大容量の生成 DB / JSON、取得可能な raw upstream data、Python cache 等を除外します。一方、`dist/charref.html` は GitHub Pages の公開成果物として追跡対象です。

`.github/workflows/pages.yml` は `main` branch への push または手動実行時に `dist/charref.html` を `index.html` として GitHub Pages へ配布します。

GitHub 側ではリポジトリ作成後に一度だけ:

1. `Settings > Pages`
2. `Build and deployment > Source`
3. **GitHub Actions** を選択

してください。GitHub Pages の公開 source は workflow 側で制御するため、`docs/` や root の branch publishing は使用しません。

通常の project repository 名が `charref` なら公開URLは概ね:

```text
https://<USER>.github.io/charref/
```

リポジトリ自体を `<USER>.github.io` という名前にした場合は user site になり:

```text
https://<USER>.github.io/
```

となります。

## 今後の課題 / 検討事項

現時点で意図的に残している主な課題です。

- **JIS90 → JIS2004 例示字形変更168字の完全リスト化**
  - 文字 code point ではなく JIS code position / glyph revision として一次資料照合を行う。
  - IVS で表現できるものは variation sequence と関連付ける。
- **78JIS → 83JIS / 83JIS → 90JIS の例示字形差の完全監査**
  - Unicode 包摂で差が消えるものを無理に別 code point 化しない。
- **ARIB追加記号の完全監査**
  - 現在の固定追加記号データを STD-B24 該当表と全件照合する。
- **ARIB 共通実装コアの根拠強化**
  - STD-B24 の coding capability と TR-B14/TR-B15 の receiver implementation requirement を明確に分ける。
- **legacy encoding mapping source の規範性強化**
  - Python runtime codec は implementation cross-check とし、可能な範囲で公式 machine-readable mapping を主 source にする。
- **WebFont**
  - 現在は Noto Sans JP / Noto Serif JP の比較表示のみ。
  - JIS2004 / IVS の検証に有用な候補を確認したうえで許可リストを拡張する。
  - font fallback や実glyph supportを推測する Font Analyzer 化は別プロジェクトとする。
- **GitHub Pages と offline build の両立**
  - Pages は配布経路であり、single HTML 自体の offline 動作を維持する。

## ライセンス / 外部データ

CharRef 本体コードと、Unicode・Microsoft・ARIB・MEXT・漢検等の外部データは同一ライセンスとは限りません。各 upstream source の利用条件を尊重してください。repository 全体へ単一ライセンスを設定する場合は、再配布するデータの条件を確認してから行ってください。
