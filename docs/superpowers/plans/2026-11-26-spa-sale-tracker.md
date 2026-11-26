# SPA 세일 트래커 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 무신사 스탠다드·유니클로·SPAO의 세일 목록과 관심 상품 가격을 하루 4회 수집하고, 관심 상품 가격이 내려가면 Gmail로 알리고, 결과를 GitHub Pages 정적 페이지로 보여준다.

**Architecture:** Python 수집기(`tracker/`)를 GitHub Actions가 스케줄 실행해 `data/*.json`을 커밋한다. 같은 워크플로가 `site/` + `data/`를 GitHub Pages로 배포한다. 브랜드별 수집 모듈은 공통 인터페이스를 구현하고 레지스트리에 등록한다.

**Tech Stack:** Python 3.12, requests, beautifulsoup4(필요한 브랜드만), pytest, smtplib(표준), GitHub Actions, GitHub Pages, 바닐라 HTML/CSS/JS.

**Spec:** `docs/superpowers/specs/2026-11-26-spa-sale-tracker-design.md`

## Global Constraints

- 저장소는 공개. 이메일 주소·비밀번호는 GitHub Secrets `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `ALERT_TO`에만 둔다. 코드·로그·커밋에 절대 출력하지 않는다.
- 스케줄: KST 08·12·18·22시 = cron `0 23,3,9,13 * * *` (UTC). `workflow_dispatch` 지원.
- 세일 = 브랜드가 판단한 `Product.on_sale`. 무신사·SPAO는 현재가 < 정가, 유니클로는 가격인하 플래그(`discount`/`limitedOffer`/`colorSizeLimitedPrice`) 존재. 유니클로는 정가를 알 수 없음(`list_price=None`). GU 상품(이름이 "GU"로 시작) 제외.
- 알림 = (a) 관심 상품 현재가 < 직전 기록가, 또는 (b) 직전 상태가 "세일 아님"(`off_sale: true`)이었는데 지금 세일 중 → "세일 시작". 첫 수집이 세일 중이면 기준값만 기록. 한 번 실행의 알림은 메일 한 통.
- 무신사는 상세 페이지가 Cloudflare로 막힘 → 목록 API만 사용. 관심 상품은 세일 목록에서 product_id로 찾고, 없으면 "세일 아님(가격 미확인)".
- 수집 경로·필드·fixture는 `docs/brand-notes.md`를 따른다.
- 수집 실패 알림 = 브랜드 세일 목록 수집 3회 연속 실패 시 1회. 성공하면 리셋.
- 가격 이력은 관심 상품만. `data/sale_items.json`은 덮어쓰기.
- 요청 간 지연 1.5초, 세일 목록 페이지 상한 브랜드당 20페이지, 요청 타임아웃 20초. User-Agent는 일반 브라우저 문자열, 개인정보 없음.
- 봇 차단 우회(프록시, 캡차 회피 등) 금지. 막히면 멈추고 사용자에게 보고.
- 재고/사이즈는 범위 밖. 단 `watchlist.txt` 한 줄에서 URL 뒤 텍스트는 무시하고 보존(향후 사이즈 확장용).

## Review Focus

1. **가격을 못 읽은 상품 페이지**(품절·삭제·404·구조 변경): 가격 0이나 None을 기록하면 가짜 하락 알림이 난다. → 해당 항목에 `last_error`만 남기고 이력·알림 없음. (Task 3, Task 8 테스트)
2. **한 브랜드만 수집 실패**: 그 브랜드 세일 상품이 화면에서 사라지면 안 된다. → 실패 브랜드는 직전 `sale_items.json` 항목 유지. (Task 8 테스트)
3. **관심 목록 URL 변형**(추적 쿼리 `?utm_...`, `#fragment`, 앞뒤 공백, 모바일 도메인, 같은 상품 중복): 같은 상품은 하나로 취급. → 정규화 후 브랜드 `product_id`로 키잉. (Task 2, 브랜드 Task 테스트)
4. **메일 발송 실패**: 이력은 이미 갱신돼 하락이 다시 알려지지 않는다. → 데이터는 저장하고 프로세스는 비정상 종료해 Actions 실패(소유자에게 GitHub 기본 실패 알림)로 드러낸다. (Task 8 테스트)
5. **사용자가 실행 중 watchlist를 편집**: push 충돌로 실행 전체가 실패. → 커밋 전 `git pull --rebase`, 워크플로 `concurrency`. (Task 9)

---

## File Structure

```
watchlist.txt                 관심 상품 URL (한 줄 하나, # 주석)
requirements.txt
tracker/
  models.py                   Product, PriceDrop
  watchlist.py                watchlist 파싱
  history.py                  관심 상품 이력 갱신, 상태(연속 실패) 갱신 — 순수 함수
  notify.py                   메일 본문 생성 + SMTP 발송
  http.py                     공용 requests 세션 + 지연
  brands/__init__.py          레지스트리, brand_for_url
  brands/base.py              Brand 프로토콜, FetchError
  brands/musinsa.py, uniqlo.py, spao.py
  run.py                      오케스트레이션 (python -m tracker.run)
data/                         sale_items.json, watch.json, status.json (수집기가 생성)
site/index.html, app.js, style.css
.github/workflows/collect.yml
docs/brand-notes.md           Task 1 조사 결과
tests/…, tests/fixtures/<brand>/…
README.md                     설치·설정 안내 (한국어)
```

### 데이터 스키마 (모든 Task 공통)

```jsonc
// data/sale_items.json
{"updated_at": "2026-11-26T23:00:00+09:00",
 "items": [ProductDict, ...]}
// data/watch.json   — 키는 "brand:product_id", 미지원/파싱 불가 URL은 키 "url:<정규화 URL>"
{"items": {"uniqlo:E465185": {
   "url": "...", "brand": "uniqlo", "name": "...", "image_url": "...",
   "list_price": 19900, "price": 14900, "on_sale": true, "off_sale": false,
   "history": [{"at": "...", "price": 19900}, {"at": "...", "price": 14900}],
   "last_error": null}}}
// list_price는 null 가능(유니클로). off_sale=true는 "세일 아님, 가격 미확인"(무신사 목록에 없음)
// data/status.json
{"brands": {"uniqlo": {"last_success": "...", "consecutive_failures": 0, "alerted": false}}}
```

`ProductDict` = `Product`의 필드 + `"discount_rate"`. 시간은 KST ISO 8601 문자열.

---

### Task 1: 브랜드별 수집 가능성 조사 (게이트)

**Files:**
- Create: `docs/brand-notes.md`, `tests/fixtures/{musinsa,uniqlo,spao}/` (세일 목록 응답 1페이지, 상품 상세 응답 2개 — 할인 중 1개, 정가 1개)
- Create: `.github/workflows/probe.yml` (임시, Task 9에서 삭제)

**Interfaces:**
- Produces: 브랜드별로 `docs/brand-notes.md`에 ① 세일 목록 경로(엔드포인트/URL, 페이지네이션 방식) ② 상품 상세 가격 경로 ③ 상품 URL 패턴과 `product_id` 추출 규칙(모바일 도메인 포함) ④ 정가·현재가 필드 ⑤ Actions에서 접근 결과. 무신사 스탠다드는 무신사 내 브랜드 `musinsastandard` 한정.

- [ ] **Step 1:** 각 사이트를 브라우저(Playwright MCP 가능)로 열고 네트워크 요청에서 세일 목록·상품 가격을 담은 JSON 엔드포인트를 찾는다. 없으면 HTML 파싱 경로를 기록한다. 헤드리스 브라우저가 필요한 경우 그렇게 기록한다.
- [ ] **Step 2:** `requests`만으로 같은 데이터를 로컬에서 받아지는지 확인하고, 응답을 fixtures로 저장한다.
- [ ] **Step 3:** `probe.yml`(workflow_dispatch, 각 브랜드 엔드포인트에 요청 1회씩, 상태 코드와 응답 앞 200자 출력)을 커밋·푸시하고 실행한다.

  Run: `gh workflow run probe.yml && gh run watch`
  Expected: 세 브랜드 모두 HTTP 200 + 기대한 데이터.
- [ ] **Step 4: 게이트.** 어떤 브랜드든 Actions에서 막히거나 헤드리스 브라우저가 필요하면 **여기서 멈추고 사용자에게 보고**한다(브랜드, 증상, 선택지). 사용자 결정을 `docs/brand-notes.md`에 기록한 뒤 진행한다.
- [ ] **Step 5: Commit** `docs: add brand scraping notes and fixtures`

### Task 2: 모델과 관심 목록 파싱

**Files:**
- Create: `requirements.txt` (`requests`, `beautifulsoup4`, `pytest`), `tracker/__init__.py`, `tracker/models.py`, `tracker/watchlist.py`, `watchlist.txt` (설명 주석 2줄만)
- Test: `tests/test_models.py`, `tests/test_watchlist.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) Product(brand: str, product_id: str, name: str, url: str, image_url: str, list_price: int | None, price: int, on_sale: bool)`; `Product.discount_rate -> int | None` (반올림 %, `list_price`가 None이거나 ≤ price면 None); `Product.to_dict() -> dict` (`discount_rate` 포함)
  - `@dataclass(frozen=True) PriceDrop(key: str, kind: str, name: str, url: str, previous: int | None, current: int, list_price: int | None, is_lowest: bool)` — `kind`는 `"drop"` 또는 `"sale_start"`
  - `parse_watchlist(text: str) -> list[str]` — 정규화된 URL 목록, 순서 유지, 중복 제거

- [ ] **Step 1: 실패하는 테스트 작성**

```python
def test_discount_rate():
    p = Product("spao", "E1", "n", "u", "i", list_price=19900, price=14900, on_sale=True)
    assert p.discount_rate == 25
def test_discount_rate_none_without_list_price():
    assert Product("uniqlo", "E1", "n", "u", "i", None, 19900, True).discount_rate is None
    assert Product("spao", "E1", "n", "u", "i", 19900, 19900, False).discount_rate is None
def test_parse_watchlist_skips_comments_blank_and_trailing_text():
    text = "# c\n\n  https://a.com/p/1?utm_source=x#top  M\nhttps://a.com/p/1\n"
    assert parse_watchlist(text) == ["https://a.com/p/1"]
```
- [ ] **Step 2:** `pytest tests -v` → FAIL (import error)
- [ ] **Step 3:** 구현. 정규화 = 첫 공백 토큰, 쿼리·fragment 제거, 끝 `/` 제거. (브랜드별 ID 키잉은 Task 5–7이 담당)
- [ ] **Step 4:** `pytest tests -v` → PASS
- [ ] **Step 5: Commit** `feat: add Product model and watchlist parser`

### Task 3: 이력·상태 갱신 로직

**Files:**
- Create: `tracker/history.py`
- Test: `tests/test_history.py`

**Interfaces:**
- Consumes: `Product`, `PriceDrop` (Task 2)
- Produces:
  - `record_price(entry: dict | None, product: Product, now: str) -> tuple[dict, PriceDrop | None]` — watch.json 항목 하나를 갱신해 새 dict 반환. `key`는 `f"{brand}:{product_id}"`.
  - `record_error(entry: dict | None, url: str, error: str) -> dict` — 이력 보존, `last_error`만 설정
  - `record_off_sale(entry: dict | None, url: str) -> dict` — "세일 아님, 가격 미확인": `off_sale=True`, `on_sale=False`, `last_error=None`, 이력 보존
  - `record_price`의 알림 규칙: (1) 직전 항목이 `off_sale=True`이고 `product.on_sale`이면 `kind="sale_start"` (이력이 없어도, `previous`는 직전 이력가 또는 None); (2) 아니면 이력이 있고 현재가 < 직전 이력가면 `kind="drop"`; (3) 그 외 None. 항상 `off_sale=False`로 갱신.
  - `update_brand_status(status: dict | None, ok: bool, now: str) -> tuple[dict, bool]` — bool = 지금 실패 알림을 보낼지
  - `FAILURE_ALERT_THRESHOLD = 3`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
def test_first_record_is_baseline_no_drop():
    e, d = record_price(None, P(price=19900), "t1")
    assert d is None and e["history"] == [{"at": "t1", "price": 19900}]
def test_same_price_not_appended_no_drop():
    e, _ = record_price(None, P(price=19900), "t1")
    e, d = record_price(e, P(price=19900), "t2")
    assert d is None and len(e["history"]) == 1
def test_drop_detected_and_lowest():
    e, _ = record_price(None, P(price=19900), "t1")
    e, d = record_price(e, P(price=14900), "t2")
    assert d.previous == 19900 and d.current == 14900 and d.is_lowest
def test_drop_after_rise_not_lowest():
    # 14900 -> 19900 -> 16900 : 하락이지만 최저가 아님
    ...
    assert d.previous == 19900 and not d.is_lowest
def test_off_sale_then_on_sale_is_sale_start():
    e = record_off_sale(None, "u")
    e, d = record_price(e, P(price=29900, on_sale=True), "t1")
    assert d.kind == "sale_start" and d.previous is None and e["off_sale"] is False
def test_off_sale_then_seen_not_on_sale_no_alert():
    e = record_off_sale(None, "u")
    e, d = record_price(e, P(price=29900, on_sale=False), "t1")
    assert d is None
def test_success_clears_last_error():
    e = record_error(None, "u", "boom"); e, _ = record_price(e, P(), "t")
    assert e["last_error"] is None
def test_record_error_keeps_history(): ...
def test_failure_alert_fires_once_at_third_then_resets():
    s = None; fired = []
    for ok in [False, False, False, False, True, False, False, False]:
        s, f = update_brand_status(s, ok, "t"); fired.append(f)
    assert fired == [False, False, True, False, False, False, False, True]
```
(`P(**kw)`는 기본값을 채운 Product 헬퍼)
- [ ] **Step 2:** `pytest tests/test_history.py -v` → FAIL
- [ ] **Step 3:** 구현. `record_price`는 `price <= 0`이면 `ValueError` (Review Focus 1). `is_lowest` = 현재가 < 기존 이력 최솟값.
- [ ] **Step 4:** `pytest tests -v` → PASS
- [ ] **Step 5: Commit** `feat: add price history and brand status logic`

### Task 4: 메일 생성·발송

**Files:**
- Create: `tracker/notify.py`
- Test: `tests/test_notify.py`

**Interfaces:**
- Consumes: `PriceDrop`
- Produces:
  - `build_drop_email(drops: list[PriceDrop]) -> tuple[str, str]` (제목, 일반 텍스트 본문)
  - `build_failure_email(brands: list[str]) -> tuple[str, str]`
  - `send_email(subject: str, body: str) -> None` — env `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `ALERT_TO`; `smtplib.SMTP_SSL("smtp.gmail.com", 465)`. env 누락 시 `MailNotConfigured` 예외.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
def test_drop_email():
    subj, body = build_drop_email([D(kind="drop", name="히트텍", previous=19900, current=14900, list_price=19900, is_lowest=True, url="https://x")])
    assert subj == "[세일 알림] 1개 상품 가격 하락"
    assert "히트텍" in body and "19,900원 → 14,900원" in body and "25%" in body and "역대 최저가" in body and "https://x" in body
def test_sale_start_email_line():
    _, body = build_drop_email([D(kind="sale_start", name="셔츠", previous=None, current=24900, list_price=29900, is_lowest=False, url="https://y")])
    assert "세일 시작" in body and "24,900원" in body and "17%" in body
def test_drop_email_without_list_price_omits_rate():
    _, body = build_drop_email([D(kind="drop", name="n", previous=19900, current=14900, list_price=None, is_lowest=False, url="u")])
    assert "%" not in body
def test_failure_email():
    subj, _ = build_failure_email(["musinsa"])
    assert subj == "[세일 트래커] musinsa 수집 3회 연속 실패"
def test_send_email_requires_env(monkeypatch):
    monkeypatch.delenv("GMAIL_ADDRESS", raising=False)
    with pytest.raises(MailNotConfigured): send_email("s", "b")
def test_send_email_uses_smtp(monkeypatch):  # smtplib.SMTP_SSL를 가짜로 바꿔 login/send_message 호출 확인
    ...
```
- [ ] **Step 2:** → FAIL
- [ ] **Step 3:** 구현. 본문 끝에 Pages 주소 한 줄(env `SITE_URL`, 없으면 생략).
- [ ] **Step 4:** `pytest tests -v` → PASS
- [ ] **Step 5: Commit** `feat: add email notifications`

### Task 5: 브랜드 기반 + 유니클로

**Files:**
- Create: `tracker/http.py`, `tracker/brands/__init__.py`, `tracker/brands/base.py`, `tracker/brands/uniqlo.py`
- Test: `tests/brands/test_uniqlo.py`, `tests/test_registry.py`

**Interfaces:**
- Consumes: `Product`, `docs/brand-notes.md`의 유니클로 항목, fixtures
- Produces:
  - `class FetchError(Exception)`
  - `class Brand(Protocol)`: `name: str`; `matches(url: str) -> bool`; `product_id(url: str) -> str`; `fetch_sale_items(session: Session) -> list[Product]`; `fetch_product(session: Session, url: str, sale_items: list[Product] | None) -> Product | None`. `None` = "세일 아님, 가격 미확인"(무신사 전용: 이번 실행의 세일 목록에서 product_id로 찾고 없으면 None; 세일 목록 수집에 실패해 `sale_items is None`이면 `FetchError`). 유니클로·SPAO는 `sale_items`를 무시하고 상세를 조회. 실패는 항상 `FetchError`(네트워크, 비정상 상태 코드, 가격 누락·0 포함).
  - `make_session() -> requests.Session` (UA, 타임아웃 20초 기본), `polite_get(session, url, **kw) -> Response` (요청 전 1.5초 지연; 테스트에서 지연 0으로 바꿀 수 있게 모듈 상수 `DELAY_SECONDS`)
  - `BRANDS: list[Brand]`, `brand_for_url(url: str) -> Brand | None`

- [ ] **Step 1: 실패하는 테스트 작성** — 파서는 네트워크 없이 fixture로 테스트한다(파싱 함수를 `parse_sale_page(raw) -> list[Product]`, `parse_product(raw, url) -> Product`로 분리).

```python
def test_parse_sale_page_returns_only_on_sale_items():
    items = uniqlo.parse_sale_page(load_fixture("uniqlo/sale_page.json"))
    assert items and all(p.on_sale and p.brand == "uniqlo" and p.list_price is None for p in items)
    assert not any(p.name.startswith("GU") for p in items)
def test_parse_product_discounted():  # fixture의 실제 값으로 기대값 작성
def test_parse_product_missing_price_raises_fetch_error():
def test_product_id_ignores_query_and_mobile_variants():  # brand-notes의 URL 변형 각각
def test_brand_for_url():
    assert brand_for_url("https://www.uniqlo.com/kr/ko/products/...").name == "uniqlo"
    assert brand_for_url("https://example.com/x") is None
```
- [ ] **Step 2:** → FAIL
- [ ] **Step 3:** 구현. `fetch_sale_items`는 페이지 상한 20, 빈 페이지에서 종료.
- [ ] **Step 4:** `pytest tests -v` → PASS
- [ ] **Step 5: Commit** `feat: add brand framework and Uniqlo scraper`

### Task 6: 무신사 스탠다드

Task 5와 같은 구조와 테스트 세트. **Files:** `tracker/brands/musinsa.py`, `tests/brands/test_musinsa.py`. `name = "musinsa"`. 세일 목록은 브랜드 `musinsastandard` 한정, DISCOUNT_RATE 정렬, 2페이지부터는 반드시 응답의 서명된 `pagination.nextPageUrl`을 따른다(직접 만든 page=N은 403). 상세 페이지는 쓰지 않는다.
- `fetch_sale_items`: 화면용으로 20페이지(또는 `saleRate == 0`)에서 멈추고, 마지막 `nextPageUrl`과 지금까지 본 상품을 인스턴스에 보관(실행마다 리셋).
- `fetch_product(session, url, sale_items)`: `sale_items is None` → FetchError. 보관한 상품에서 product_id를 찾고, 없으면 보관한 `nextPageUrl`부터 이어서 페이지를 넘기며(넘긴 페이지도 보관해 다음 관심 상품이 재사용) 찾는다. 찾으면 Product, `saleRate == 0` 또는 목록 끝에 도달하면 None("세일 아님"), 총 150페이지 상한에 걸리면 FetchError("목록 상한 도달, 확인 불가") — 상한에서 None을 돌려주면 세일 중인 상품이 "세일 아님"이 됐다가 가짜 "세일 시작" 알림이 나기 때문.
- 테스트: fixture(`sale_list_discount_page1.json`, `sale_list_discount_tail.json`)와 가짜 세션으로 — 20페이지 이후에서 발견, saleRate 0에서 None, 상한에서 FetchError, 두 관심 상품이 페이지를 다시 받지 않음, `sale_items is None` → FetchError.
`BRANDS`에 등록. Commit `feat: add Musinsa Standard scraper`. (Task 1 게이트에서 제외로 결정되면 이 Task는 건너뛴다.)

### Task 7: SPAO

Task 5와 같은 구조와 테스트 세트. **Files:** `tracker/brands/spao.py`, `tests/brands/test_spao.py`. `name = "spao"`. `BRANDS`에 등록. Commit `feat: add SPAO scraper`.

### Task 8: 실행 오케스트레이션

**Files:**
- Create: `tracker/run.py`
- Test: `tests/test_run.py`

**Interfaces:**
- Consumes: Task 2–7 전부
- Produces: `run(root: Path, now: str, brands: list[Brand], session, send=send_email) -> int` (종료 코드), `main()` (`python -m tracker.run`, 현재 KST 시각으로 `run` 호출 후 `sys.exit`)

처리 순서:
1. `data/*.json` 읽기(없으면 빈 구조).
2. 브랜드마다 `fetch_sale_items` → 성공 시 그 브랜드 항목 교체, 실패 시 직전 항목 유지. `update_brand_status`로 실패 알림 대상 수집.
3. `watchlist.txt`의 각 URL: 브랜드 없음 → `record_error(..., "지원하지 않는 브랜드")`; `fetch_product(session, url, 이번 실행에서 그 브랜드 세일 목록 수집 성공 시 그 목록, 실패 시 None)` → Product면 `record_price`, None이면 `record_off_sale`; `FetchError` → `record_error`. watchlist에서 빠진 키는 `watch.json`에서 제거.
4. JSON 세 파일 저장(정렬된 키, `ensure_ascii=False`, indent 2). 세일 목록은 할인율 내림차순.
5. 하락이 있으면 하락 메일, 실패 알림 대상이 있으면 실패 메일. `MailNotConfigured`면 경고만 출력하고 0. 발송 예외면 1 반환(데이터는 이미 저장됨).

- [ ] **Step 1: 실패하는 테스트 작성** — 가짜 Brand 두 개와 `tmp_path`, 기록용 가짜 `send` 사용.

```python
def test_first_run_records_baseline_without_email(tmp_path): ...  # sent == []
def test_drop_sends_one_email_for_all_drops(tmp_path): ...       # 두 상품 하락 → len(sent) == 1
def test_failed_brand_keeps_previous_sale_items(tmp_path): ...   # Review Focus 2
def test_unreadable_price_sets_error_no_email(tmp_path): ...     # Review Focus 1
def test_same_product_two_url_variants_is_one_entry(tmp_path): ...  # Review Focus 3
def test_unsupported_url_recorded_as_error(tmp_path): ...
def test_removed_watchlist_url_dropped(tmp_path): ...
def test_send_failure_saves_data_and_returns_1(tmp_path): ...    # Review Focus 4
def test_third_consecutive_failure_sends_failure_email(tmp_path): ...
def test_watched_item_absent_then_in_sale_list_sends_sale_start(tmp_path): ...  # 무신사형 가짜 브랜드, 두 번 실행
def test_sale_list_failure_does_not_mark_watched_off_sale(tmp_path): ...  # sale_items None → FetchError → last_error, off_sale 상태 변화 없음
```
- [ ] **Step 2:** → FAIL
- [ ] **Step 3:** 구현
- [ ] **Step 4:** `pytest tests -v` → 전부 PASS
- [ ] **Step 5: 실제 실행** `python -m tracker.run` (메일 env 없이) → `data/` 세 파일 생성, 세 브랜드 모두 `consecutive_failures == 0`, `sale_items.json` 항목 > 0.
- [ ] **Step 6: Commit** `feat: add collection runner` (생성된 `data/` 포함)

### Task 9: GitHub Actions 워크플로

**Files:**
- Create: `.github/workflows/collect.yml`
- Delete: `.github/workflows/probe.yml`

**Interfaces:**
- Consumes: `python -m tracker.run`, `site/`, `data/`

구성:
- 트리거: `schedule` (`0 23,3,9,13 * * *`), `workflow_dispatch`, `push` (paths: `watchlist.txt`, `site/**`, `tracker/**`).
- `concurrency: {group: collect, cancel-in-progress: false}`; `permissions: contents: write, pages: write, id-token: write`.
- Job `collect`: checkout → setup-python 3.12 → `pip install -r requirements.txt` → `pytest -q` → `python -m tracker.run` (env: 세 Secrets + `SITE_URL`) → `data/` 변경 시 `git pull --rebase` 후 커밋 `chore: update data [skip ci]`·푸시. 수집기가 1을 반환해도 커밋 스텝은 실행(`if: always()`)하고, 마지막에 잡을 실패로 표시.
- Job `deploy` (needs collect, `if: always()`): 최신 main checkout → `site/`와 `data/`를 `_site/`로 복사(`_site/data/`) → `actions/upload-pages-artifact` → `actions/deploy-pages`.

- [ ] **Step 1:** 워크플로 작성, probe 삭제, 푸시.
- [ ] **Step 2:** 저장소 Settings → Pages → Source를 "GitHub Actions"로 설정(사용자 작업 필요 시 안내). `gh workflow run collect.yml && gh run watch` → 두 잡 성공, `data/` 커밋 생성.
- [ ] **Step 3:** 실행 중 `watchlist.txt`를 따로 커밋해 동시 실행해도 둘 다 성공하는지 확인(Review Focus 5).
- [ ] **Step 4: Commit** `ci: add scheduled collect and deploy workflow`

### Task 10: 화면

**Files:**
- Create: `site/index.html`, `site/style.css`, `site/app.js`

**Interfaces:**
- Consumes: `data/sale_items.json`, `data/watch.json`, `data/status.json` (페이지 기준 경로 `data/…`)

내용(스펙 화면 스케치 기준):
- 상단: 검색어, 브랜드, 최소 할인율, 최대 가격 필터. 필터는 둘러보기 영역에만 적용.
- 관심 상품: 카드마다 이미지, 이름, 현재가, 정가, 할인율, 이력 기반 인라인 SVG 스파크라인, 현재가 == 이력 최솟값이고 이력 2개 이상이면 "최저가" 배지. `last_error`가 있으면 오류 문구와 원본 링크.
- `discount_rate`가 null인 상품(유니클로)은 할인율 대신 "가격인하" 배지, 정가 줄은 생략. 관심 상품의 `off_sale`이면 "세일 아님" 표시.
- 둘러보기: 할인율 내림차순 카드 그리드(할인율 null은 맨 뒤, 그 안에서는 가격 오름차순). 최소 할인율 필터를 걸면 null 상품은 제외. 카드의 "관심 추가" = `navigator.clipboard.writeText(url)` 후 `https://github.com/<owner>/<repo>/edit/main/watchlist.txt`를 새 탭으로 연다. owner/repo는 `app.js` 상단 상수.
- 하단(또는 상단 작은 글씨): 브랜드별 마지막 수집 시각, 실패 중이면 경고 표시.
- 모바일 우선 반응형, 라이트/다크 대응. 이미지는 `loading="lazy"`.

- [ ] **Step 1:** 구현.
- [ ] **Step 2:** 로컬 확인: `_site/` 구성과 같게 `site/`와 `data/`를 임시 폴더에 복사하고 `python -m http.server`로 띄운 뒤 Playwright로 375px·1280px 스크린샷. 확인 항목: 관심 상품 영역 표시, 필터가 개수를 줄임, "관심 추가"가 편집 URL을 염, 데이터 파일이 비어 있어도 오류 없이 빈 상태 문구 표시.
- [ ] **Step 3: Commit** `feat: add sale tracker page`

### Task 11: 설정 안내와 실제 운영 확인

**Files:**
- Create: `README.md` (한국어)

- [ ] **Step 1:** README 작성: 무엇을 하는지, Gmail 2단계 인증 + 앱 비밀번호 만들기, Secrets 세 개(+ 선택 `SITE_URL`) 등록, Pages 소스 설정, 관심 상품 추가 방법(`watchlist.txt` 형식 예시), 수동 실행 방법, 브랜드 추가 방법(`tracker/brands/` 모듈 + `BRANDS` 등록).
- [ ] **Step 2:** 사용자에게 Secrets 등록을 요청. 등록 후 실제 상품 1개를 watchlist에 넣고 실행 → 기준값 기록 확인. 하락 메일 경로는 `watch.json`의 해당 상품 직전 가격을 임시로 높여 커밋한 뒤 실행해 메일 수신을 사용자와 확인하고, 임시 수정은 다음 실행에서 자연히 덮인다.
- [ ] **Step 3:** Pages 주소에서 화면이 실제 데이터로 보이는지 확인.
- [ ] **Step 4: Commit** `docs: add setup guide`
