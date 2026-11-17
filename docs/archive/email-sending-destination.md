# SA Dashboard 이메일 발송 destinations

## 규칙
SA 관련 파일/문서 이메일 발송 시 **반드시** `hermes.asusada@gmail.com`으로 발송.

## 왜?
- 이 주소는 SA dashboard 시스템 계정 (DB + FastAPI 연동).
- 사용자 개인 이메일 주소와 다름.
- 사용자가 별도로 지시하지 않으면 다른 주소로 임의 발송 금지.

## 실수 사례 (2026-05-21)
사용자가 "나한테 파일로 보내줘" 요청 → 에이전트가 `raymond@handsup.co.kr`로 발송.
사용자: "메일 왜 아무데나 보내냐. 아까 보냈던데로 보내"
→ `hermes.asusada@gmail.com`으로 재발송.

## 교훈
"나한테 보내줘"라는 표현이 개인 이메일을 의미하는지 SA dashboard 계정을 의미하는지 불명확할 때:
1. SA 관련 작업이면 기본값: `hermes.asusada@gmail.com`
2. 불확실하면 사용자에게 확인 ("어디로 보내드릴까요?")
