# SA News Dashboard — 배포/운영 구성

코드는 이 repo에 있지만, **실제 파이프라인을 굴리는 글루(cron 셔임·스케줄)** 는
hermes gateway 쪽에 있습니다. 머신 재구성/이전 시 이 문서로 복원합니다.

## 구성 요소
| 구분 | 위치 |
|---|---|
| 코드 | `~/Documents/sa-dashboard/` (이 repo) |
| 실행 셔임(활성) | `~/.hermes/scripts/sa_{collect,publish,purge}.sh` |
| 셔임 버전관리 사본 | `deploy/hermes-scripts/` (이 디렉토리) — 활성본과 동기 유지 |
| 스케줄 | hermes cron (`hermes cron list`) |
| 웹서버 | launchd `com.user.sa-dashboard` (port 8181) |
| Python | `~/Documents/sa-dashboard/venv/bin/python3` (collect/publish/purge 모두 venv 통일) |

## cron 작업 (hermes)
| name | 스케줄 | 셔임 | 모드 |
|---|---|---|---|
| sa-collect | `0,30 * * * *` (30분마다) | sa_collect.sh | no-agent, deliver=local |
| sa-publish | `10,40 * * * *` (collect +10분) | sa_publish.sh → `sa_summarize_claude.py --batch 10` | no-agent, deliver=local |
| sa-purge | `30 3 * * *` (매일 03:30) | sa_purge.sh → `sa_purge_deleted.py --days 30` | no-agent, deliver=local |

- collect → publish 순서 전제(collect가 10분 내 완료). 각 잡은 `fcntl` 단일 인스턴스 락으로
  틱 겹침을 방지(`scripts/sa_lock.py`) — 이전 배치가 돌고 있으면 다음 틱은 skip.
- no-agent + deliver=local: **스크립트 stdout이 곧 전달 페이로드**. 요약/진단 출력은
  stdout(사람이 볼 요약) vs stderr(오류/skip)로 분리. purge는 0건이면 무음.

## 셔임 재등록 (복원 시)
```bash
# 1. 셔임 배치
cp deploy/hermes-scripts/*.sh ~/.hermes/scripts/ && chmod +x ~/.hermes/scripts/sa_*.sh
# 2. cron 등록
hermes cron create "0,30 * * * *" --name sa-collect --script sa_collect.sh --no-agent --deliver local
hermes cron create "10,40 * * * *" --name sa-publish --script sa_publish.sh --no-agent --deliver local
hermes cron create "30 3 * * *"    --name sa-purge   --script sa_purge.sh   --no-agent --deliver local
```

## 셔임 변경 시
활성본(`~/.hermes/scripts/`)을 고치면 **반드시 `deploy/hermes-scripts/`에도 반영**해 동기 유지.
