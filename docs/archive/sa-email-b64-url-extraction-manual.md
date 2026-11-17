# SA 이메일 base64 URL 추출 패턴 (이미 읽은 이메일용)

## 배경

`extract_sa_urls.py`는 미읽음 이메일만 처리하므로, 이미 읽음 처리된 SA 이메일은 스크립트로 URL을 추출할 수 없음. 이 경우 himalaya로 이메일 본문을 직접 읽어서 base64 인코딩된 URL을 추출해야 함.

## SA 이메일 URL 구조

SA 이메일(`seekingalpha@mail.sailthru.com`)의 본문에는 article URL이 base64 인코딩되어 포함됨.

- 인코딩된 URL은 `aHR0`로 시작 (base64 for `http`)
- 패턴: `aHR0[sA-Za-z0-9+/=]+`
- 디코딩 결과: `https://seekingalpha.com/news/48123456-abc-def-ghi`

## 추출 워크플로우

### 1. 이메일 본문 읽기

```bash
himalaya message read <EMAIL_ID>
```

출력에서 base64 URL 패턴 추출:

```bash
himalaya message read 705 | grep -o 'aHR0[sA-Za-z0-9+/=]*'
```

### 2. Base64 디코딩

```bash
# 단일 URL
echo 'aHR0cHM6Ly9zZWVraW5nYWxwaGEuY29tL25ld3MvNDg5MjM0NQ==' | base64 -d

# 파이프라인 (한 번에)
himalaya message read 705 | grep -o 'aHR0[sA-Za-z0-9+/=]*' | while read b64; do echo "$b64" | base64 -d; done
```

### 3. URL 필터링

디코딩 결과에서 `seekingalpha.com/news/` 패턴만 필터:

```bash
himalaya message read 705 | grep -o 'aHR0[sA-Za-z0-9+/=]*' | while read b64; do
    decoded=$(echo "$b64" | base64 -d 2>/dev/null)
    if echo "$decoded" | grep -q 'seekingalpha.com/news/'; then
        echo "$decoded"
    fi
done
```

### 4. Python 대체方案

```python
import base64
import re

email_body = """...himalaya message read 결과..."""
b64_urls = re.findall(r'aHR0[sA-Za-z0-9+/=]+', email_body)
for b64 in b64_urls:
    try:
        decoded = base64.b64decode(b64).decode('utf-8')
        if 'seekingalpha.com/news/' in decoded:
            print(decoded)
    except Exception:
        pass
```

## 주의사항

- SA 이메일 본문이 길 경우(~17K chars) himalaya message read 출력이 크므로 grep으로 빠르게 필터링
- 일부 이메일은 여러 URL을 포함할 수 있음 — `news/` 패턴으로 필터링하여 정확한 article URL만 선택
- 디코딩 실패(`base64 -d` error)는 무시하고 다음 URL로 진행
- 추출된 URL은 `parse_sa_article()` 호출 전 `unquote()` 처리 필요 (percent-encoded URL일 수 있음)

## 관련

- `scripts/extract_sa_urls.py` — 자동 미읽음 처리 (기본 워크플로우)
- `scripts/sa_article_parser.py` — URL 파싱
- SKILL.md: "이미 읽은/누락된 SA 이메일 수동 처리" 섹션
