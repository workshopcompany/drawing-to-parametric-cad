# web_ui.py 사용법

## 이게 뭔가요
run_pipeline.py를 명령창이 아니라 브라우저에서 쓰는 작은 화면입니다.
표준 라이브러리만 써서, 별도 설치가 필요 없습니다.

## 시작 방법
orchestrator 폴더( run_pipeline.py가 있는 폴더 )에서:
- Windows: `python web_ui.py`
- Mac/Linux: `python3 web_ui.py`
그 뒤 브라우저에서 http://127.0.0.1:8000/ 을 여세요.
포트를 바꾸려면 `python web_ui.py --port 8001` 처럼 실행합니다.

## 폼 항목
- 도면 이미지: 업로드하면 출력 폴더에 input_drawing.확장자로 저장됩니다.
  결과 페이지에서 브라우저로 직접 볼 수 있습니다.
- 윤곽 첨부 (선택): 윤곽 스냅 도구에서 뽑은 JSON, 또는 윤곽 이미지.
  JSON은 요약해서 LLM 프롬프트에 넣고(전체 1202점을 그대로 넣지 않음),
  이미지는 두 번째 이미지로 LLM에 보냅니다. 원본은 출력 폴더에
  outline_input.* 으로 보관됩니다.
- 부품 설명: 선택, 도면에 대한 메모를 적습니다.
- 기어 부품: 기어일 때만 체크하세요. 그때만 기어 참조가 포함됩니다.
- 출력 폴더: 기본 ./my_run_output, 서버를 시작한 폴더 기준입니다.
- freecadcmd: 기본 freecadcmd, PATH에 없으면 경로를 입력하세요.
- dry-run: API 호출 없이 프롬프트 조립만 확인합니다.
- Meta API 키: 비밀번호 칸, 저장되지 않고 이번 실행에만 쓰입니다.
  키 칸을 비우면 레포 폴더의 .env 파일 키를 씁니다. .env 만드는 법:
  .env.example을 .env로 복사하고 META_API_KEY= 뒤에 본인 키를 넣으세요.
  .env는 절대 깃허브에 올리지 마세요 (.gitignore가 막습니다).
  폼에는 .env 키 있음/없음만 표시되고, 키 값은 표시되지 않습니다.

## 먼저 dry-run부터
처음엔 dry-run을 체크하고 실행하세요. 프롬프트 조립이 되는지,
report.txt와 prompt_dryrun.txt가 출력 폴더에 생기는지 확인합니다.

## 결과 확인
실행이 끝나면 결과 페이지에 종료 코드, report.txt, guidance.txt(실패 시),
입력 이미지, 결과 프리뷰, 출력 파일 목록과 다운로드 링크가 나옵니다.
결과 프리뷰(preview_iso.png, preview_main.png)는 STEP 테셀레이션에서
만든 음영 이미지로, 치수 도면이 아니라 형상 확인용입니다. .fcstd는
FreeCAD GUI로 열어 트리, 완전구속, 치수 변경 후 다시 계산되는지
확인하세요. 프리뷰를 못 만들면(예: matplotlib 없음) 실행 자체는
실패하지 않고, 보고서에 "Previews: unavailable"이라고만 남습니다.

## 키 보안
키는 디스크에 저장되지 않고, 로그·URL·결과 페이지에 나타나지 않으며,
run_pipeline.py에는 환경변수(META_API_KEY)로만 전달됩니다. 키 칸이
비어 있고 .env 키도 없고 dry-run이 아니면 실행하지 않습니다.
.env 파일 자체도 다운로드로 제공할 수 없습니다 (출력 폴더 밖 파일은
다운로드가 막혀 있습니다).

## 윤곽 도구
outline_snap_tool.html을 브라우저로 열면, 도면 위에 윤곽을 직접 그려서
JSON으로 뽑을 수 있습니다. 이 파일은 test/test2_snap_tool.html의
복사본입니다. test/ 원본은 test2 당시 기록본이라 그대로 두고,
앞으로 윤곽 도구를 고칠 때는 orchestrator/ 복사본만 고칩니다.

## 솔직한 한계
이 UI는 사용자의 PC에서만 돌아갑니다. Muse가 이 PC를 조종하게 하지
않으며, FreeCAD를 대신하지도 않습니다. FreeCAD 1.1.4가 별도로
필요합니다. 실제 API 실행은 사용자의 키로 집에서 테스트해야 합니다.
