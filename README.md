# 다시만날별

Toss 미니앱 백엔드입니다. 배포 주소: https://dasi-mannal-byeol.onrender.com

## Keep-alive

Render 무료 인스턴스는 약 15분 동안 요청이 없으면 잠들 수 있고, 잠든 뒤의 첫 접속은 응답이 늦어집니다. `.github/workflows/keepalive.yml` 워크플로(Keep Render alive)가 `GET /api/health`와 `GET /api/pets`를 호출합니다. health는 프로세스가 HTTP 응답을 보낼 수 있는지만 보고, pets는 첫 화면의 별자리 목록이 열리는지 봅니다. 각 요청 제한 시간은 20초이고, 실패하면 최대 2번 더 시도합니다. 둘 중 하나라도 HTTP 200이 아니면 작업은 실패합니다. Actions 탭에서 같은 워크플로를 수동으로 실행할 수도 있습니다. 예약 실행은 기본 브랜치에 머지된 워크플로만 동작합니다.

GitHub 예약 워크플로는 부하가 있으면 늦어지거나 건너뛸 수 있습니다. 10분 cron이 기록상 그보다 길게 비는 경우가 있어, 그 간격만으로 15분 잠금을 항상 막지는 못합니다.

GitHub는 저장소에 60일 동안 활동(커밋, 이슈, 풀 리퀘스트 등)이 없으면 예약된 워크플로를 자동으로 비활성화합니다. 비활성화되면 Actions 탭에서 이 워크플로를 다시 켜야 keep-alive가 이어집니다.

## 관리자 집계

신규 별자리 수는 https://dasi-mannal-byeol.onrender.com/#/admin 에서 확인합니다. API는 `GET /api/admin/summary` 이고, 헤더 `X-Admin-Token`이 환경 변수 `ADMIN_TOKEN`과 같아야 합니다. 응답은 예시가 아닌 별자리의 개수, 공개 범위별 개수, 최근 24시간·7일 개수, 가장 최근 등록 시각만 담습니다. 광장과 `GET /api/pets`에는 전체공개 별자리만 나옵니다.

같은 토큰을 쓰는 기존 관리 API는 `POST /api/admin/rewatermark/<id>` 입니다.
