# 브랜드별 수집 가능성 조사 (Task 1)

조사일: 2026-11-26. 공통: `requests` + 일반 브라우저 User-Agent, 요청 간 2초 지연, timeout 20초. 헤드리스 브라우저는 세 브랜드 모두 불필요(아래 무신사 상품 상세 HTML 제외).

Actions 접근 결과: run 45779959002 (ubuntu-latest, `probe.yml`, push 트리거).

| 대상 | 로컬 | Actions |
|---|---|---|
| 무신사 세일 목록 API | 200 | 200 |
| 무신사 상품 상세 HTML | 200/403 간헐 (Cloudflare) | **403 (Cloudflare 차단 페이지)** |
| 유니클로 목록 API | 200 | 200 |
| 유니클로 상세 API | 200 | 200 |
| SPAO 세일 목록 API | 200 | 200 |
| SPAO 상품 상세 HTML | 200 | 200 (`orgSellPrice`/`sellPrice` 추출 확인) |

## 1. 무신사 스탠다드 (브랜드 slug `musinsastandard`)

① 세일 목록 (JSON)
- `GET https://api.musinsa.com/api2/dp/v2/plp/goods?gf=A&sortCode=DISCOUNT_RATE&brand=musinsastandard&page=1&size=30&caller=FLAGSHIP`
- `brand=musinsastandard` 로 브랜드 한정. `saleYn=Y` 파라미터는 서버가 무시함(전체 7133개 반환). 대신 `sortCode=DISCOUNT_RATE`(할인율 내림차순)로 정렬하고 `saleRate == 0` 인 상품이 나오면 페이지 순회를 중단한다.
- 페이지네이션: `page`(1부터), `size`(30 사용 확인). 응답 `data.pagination` = `{page,size,totalCount,totalPages,hasNext,nextPageUrl}`. `hasNext` 로 종료 판단.
- 그 외 sortCode: `SALE_RATE`, `POPULAR`, `NEW` 도 동작하나 할인 정렬이 아님(`SALE_RATE`는 인기순과 동일하게 보임).

② 상품 가격 경로: 목록 응답 자체에 정가/현재가가 있으므로 상세 호출이 필요 없다(권장).
- 상세 HTML `https://www.musinsa.com/products/{goodsNo}` 의 `__NEXT_DATA__` → `props.pageProps.dehydratedState.queries[0].state.data.data.goodsPrice` (`normalPrice`, `salePrice`, `discountRate`, `isSale`, `finalPrice`) 로 값은 있으나 **Cloudflare 가 Actions IP 를 403 으로 차단**하고 로컬에서도 간헐적 403. `goods-detail.musinsa.com/api2/goods/{id}` JSON 도 로컬에서 403. => 상세 페이지에 의존하지 않는다. 가격 추적은 목록 API만으로 설계할 것(세일 목록에서 빠진 상품은 "할인 종료"로 간주, 정가 확인이 필요하면 `sortCode` 순회 대신 brand 목록 전체 순회가 필요).

③ 상품 URL / product_id
- URL: `https://www.musinsa.com/products/{goodsNo}` (목록 필드 `goodsLinkUrl`). 구형 `https://www.musinsa.com/app/goods/{goodsNo}` 는 302 로 위 URL 로 리다이렉트. 모바일 `https://m.musinsa.com/products/{goodsNo}` 도 200.
- 추출 규칙: 정규식 `/(?:products|goods)/(\d+)` → `goodsNo`(정수). 목록에서는 `goodsNo` 필드를 그대로 사용.

④ 필드 (목록 `data.list[]`)
- 정가: `normalPrice`, 현재가(할인 적용): `price` (쿠폰 등 추가 반영 `finalPrice`, 없으면 `price`와 같음), 할인율: `saleRate`(정수 %), 품절: `isSoldOut`, 이름: `goodsName`, 이미지: `thumbnail`, 브랜드: `brand`.
- 쿠폰가 `couponPrice`/`couponSaleRate` 는 null 인 경우가 많음. 추적 기준은 `price` 권장.

⑤ Actions 접근: 목록 API 200 (27 KB, 기대 JSON). 상세 HTML 403 (Cloudflare).

Fixtures
- `tests/fixtures/musinsa/sale_list_page1.json` (sortCode=SALE_RATE 1페이지 중 할인 4개 + 정가 3개로 축약. 이 파일은 할인/정가 혼합 목록 파서 테스트용)
- `tests/fixtures/musinsa/product_sale.html` (goodsNo 2463944, 정가 59900/판매가 5990), `product_full.html` (goodsNo 7515788, 69900/69900). 상세 HTML 은 위 이유로 사용 비권장(참고용, `__NEXT_DATA__` 만 남긴 축약본).

## 2. 유니클로 한국 (`https://www.uniqlo.com/kr/ko/`)

① 세일 목록 (JSON, 로그인/쿠키 불필요)
- `GET https://www.uniqlo.com/kr/api/commerce/v5/ko/products?path=&flagCodes=discount&limit=36&offset=0&httpFailure=true`
- `flagCodes=discount` = "가격인하", `limitedOffer` = "기간한정". 둘을 같이 받으려면 `flagCodes=discount,limitedOffer` (현재 404 + 16 = 420건; `limitedOffer` 와 `discount` 는 대부분 겹치지 않음). `limit` 은 100까지 확인.
- 페이지네이션: `offset`/`limit`, 응답 `result.pagination` = `{total, offset, count}`. `offset + count >= total` 이면 종료.
- 목록에 GU 상품(ID가 `E4...`로 같은 형식)도 섞여 있음(이름이 `GU...` 로 시작). 필요하면 이름 접두어로 제외.

② 상품 상세 가격
- `GET https://www.uniqlo.com/kr/api/commerce/v5/ko/products/{productId}/price-groups/00/details?withPrices=true&withStocks=true&includeModelSize=false&httpFailure=true` → `result.prices`
- 사이즈/컬러별 가격: `.../price-groups/00/l2s?withPrices=true&withStocks=true` → `result.prices[l2Id]`.

③ 상품 URL / product_id
- `https://www.uniqlo.com/kr/ko/products/{productId}/00?colorDisplayCode=07` 예: `E486821-000`. 모바일 도메인 없음(반응형 동일 도메인).
- 추출 규칙: 정규식 `/products/(E\d{6}-\d{3})`; 목록 필드는 `productId`.

④ 가격 필드: `prices.base.value`(KRW 정수), `prices.promo.value`(없으면 `null`)
- **중요(제약)**: 유니클로 KR 은 "가격인하" 상품에서도 `base == promo == 현재가` 로 내려오며, API 어디에도 인하 전 정가가 없음 (목록/상세/`l2s` 모두 확인, 420건 전수에서 `promo < base` 인 상품 0개). 인하 사실은 `representative.flags.priceFlags[]` 의 `code`(`discount`/`limitedOffer`/`colorSizeLimitedPrice`) 와 `name`("2026/11/24부터 가격인하"), `effectiveTime.start`(epoch 초) 로만 알 수 있다.
- 정가(할인 전 가격)가 필요하면 **우리 DB 에 쌓은 이력에서 가장 높은 가격/최초 관측가를 정가로 사용**해야 한다. 플래그가 없는 정상가 상품은 `promo: null`, `priceFlags: []`.
- 따라서 "세일 여부" 판정 = `priceFlags` 에 `discount` 또는 `limitedOffer` 존재. "할인율" 은 이력이 쌓인 뒤에만 계산 가능 (설계 조정 필요, 컨트롤러에 보고).

⑤ Actions 접근: 목록 200 (151 KB), 상세 200.

Fixtures
- `tests/fixtures/uniqlo/sale_list_page1.json` (8개 축약, 이미지/사이즈 제거), `product_sale.json` (E486821-000, 79900, flags=discount), `product_full.json` (E465187-000, 7900, promo=null, 플래그 없음)

## 3. SPAO (`https://www.spao.com`)

① 세일 목록 (JSON)
- `GET https://www.spao.com/api/item/sale?size=100&dispLctgNo=2605000005&sort=40&page=1` (사이트의 /u/sale "기간할인" 페이지가 쓰는 XHR 그대로). `dispLctgNo=2605000005` 는 사이트 전체 루트 카테고리(필수; 생략하면 빈 목록).
- 페이지네이션: `page`(1부터), `size`=100. 응답 `data` 배열 길이 < `size` 이면 마지막 페이지. 현재 총 596건(6페이지). (`pageNo`, `offset` 은 무시됨.)
- 응답 형태: `{resultCode, resultMessage, data:[...]}`.

② 상품 상세 가격: 목록 응답에 이미 정가/판매가 포함. 상세 HTML(`/i/item?itemNo=..&lowerVendNo=..`)도 200 이며 인라인 JSON `"priceInfo":{"orgSellPrice":59900,"sellPrice":53910,"dcRate":10,...}` 와 ld+json `offers.price` 가 있음(Actions 에서도 확인).

③ 상품 URL / product_id
- `https://www.spao.com/i/item?itemNo={itemNo}&lowerVendNo={LV...}`. 모바일 별도 도메인은 확인 못함(반응형 동일 도메인 추정, `m.spao.com` 미확인).
- 추출 규칙: 쿼리 파라미터 `itemNo` (10자리 숫자 문자열). 목록 필드는 `itemNo`.

④ 필드(목록 `data[]`): 정가 `orgSellprice`, 현재가 `sellprice`(= `finalDcPrice`), 할인율 `dcRate`, 이름 `itemName`, 이미지 `representImagePath`(앞에 이미지 CDN 호스트 필요; 목록에는 상대경로 `r/image/item/...`). 주의: 목록의 키는 소문자 p(`orgSellprice`/`sellprice`), 상세 HTML 의 `priceInfo` 는 대문자 P(`orgSellPrice`/`sellPrice`).
- 정가 상품(할인 없음): `sellprice == orgSellprice` (예: itemNo 2611025016 `49900/49900`), `applyEndTs` 는 `9999-12-31`.

⑤ Actions 접근: 목록 200 (272 KB), 상세 HTML 200.

Fixtures
- `tests/fixtures/spao/sale_list_page1.json` (8개 축약, 이미지 1장), `product_sale.html` (itemNo 2607013428, 59900→53910), `product_full.html` (itemNo 2611025016, 정가 49900/49900). 상세 HTML 은 ld+json Product 와 `priceInfo` 만 남긴 축약본.

## 게이트 결과

- 헤드리스 브라우저 필요: 없음. 모든 브랜드가 JSON API 또는 SSR HTML 로 수집 가능.
- Actions 에서 막힌 대상: 무신사 **상품 상세 HTML 1건만** (Cloudflare 403). 무신사는 목록 API 만 사용하면 되므로 수집 자체는 가능. 사용자 판단 필요: 무신사 "정가 상태 상품"의 가격 이력은 목록 순회로만 확인 가능(아래 설계 영향).
- 설계 영향 2건: (a) 유니클로 정가(인하 전 가격) 미제공 → 이력 기반 정가 추정 필요, (b) 무신사 상세 페이지 사용 불가 → 목록 API 기반으로 가격 갱신.
