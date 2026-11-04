# 다시만날별

Toss 미니앱 백엔드입니다. 배포 주소: https://dasi-mannal-byeol.onrender.com

## Keep-alive

Render 무료 인스턴스는 약 15분 동안 요청이 없으면 잠들고, 다음 첫 접속은 10초 이상 걸립니다. `.github/workflows/keepalive.yml` 워크플로(Keep Render alive)가 10분마다 `GET /api/pets`를 호출해 인스턴스를 깨워 둡니다. 제한 시간은 60초이고, 실패하면 최대 3번 다시 시도합니다. 응답이 HTTP 200이 아니면 작업은 실패합니다. Actions 탭에서 같은 워크플로를 수동으로 실행할 수도 있습니다. 예약 실행은 기본 브랜치에 머지된 워크플로만 동작합니다.

GitHub는 저장소에 60일 동안 활동(커밋, 이슈, 풀 리퀘스트 등)이 없으면 예약된 워크플로를 자동으로 비활성화합니다. 비활성화되면 Actions 탭에서 이 워크플로를 다시 켜야 keep-alive가 이어집니다.
