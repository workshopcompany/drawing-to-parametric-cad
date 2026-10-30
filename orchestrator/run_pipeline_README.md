# run_pipeline.py 사용법 (v0.1 프로토타입)

## 이게 뭐야?
도면 이미지 + 텍스트를 넣으면, Meta API가 FreeCAD 매크로를 만들고,
FreeCAD가 실행해서 .fcstd + STEP + 보고서를 내보내는 오케스트레이터야.
지금은 채팅에서 나눠서 하던 일을 하나의 스크립트로 묶은 버전이야.

## 다운받을 것
- FreeCAD 1.1.4 (무료)
- 이 레포 zip (orchestrator/ 폴더에 실행에 필요한 파일이 다 들어 있어)
- META_API_KEY (Meta 개발자 포털에서 받는 키, 코드에 절대 박지 마)

## 실행 방법 (한 줄)
orchestrator 폴더에서 실행해:
```
cd orchestrator
export META_API_KEY="..."
python3 run_pipeline.py --drawing my_drawing.png --text "부품 설명" --output-dir ./my_run_output
```
기어가 들어간 도면이면 `--gear`를 붙여. 기어가 아니면 붙이지 마.

## 결과 확인 (FreeCAD GUI에서)
- `<output-dir>/model.fcstd`를 열어.
- 트리가 Body → Sketch → Pad/Pocket 순서인지 확인해.
- 각 스케치가 FullyConstrained인지, 치수가 도면과 맞는지 확인해.
- 치수 하나를 바꿔서 다시 계산(Recompute)해봐. 단일 유효 솔리드로
  다시 만들어지면 파라메트릭이 살아있는 거야.
- `<output-dir>/model.step`도 열어보고, 같은 모양인지 확인해.
- `<output-dir>/report.txt`에 솔리드 개수, 유효 여부, 박스, 부피(참고만)가 있어.
- 부피만으로는 합격 판정을 안 해. 솔리드가 정확히 1개이고 유효해야 해.

## 실패하면?
- 코드/API 오류는 최대 3회까지 스스로 고쳐서 다시 실행해.
- 3회째 실패하면 멈추고 `<output-dir>/guidance.txt`에 피처 이름,
  기하 번호, 정확한 오류, 원인, 질문/대안을 적어.
- 설계/치수 질문이 나오면 치수를 지어내지 않고 멈춰. 답을 주고 다시 실행해.

## 질문 먼저 (--ask-first)
`--ask-first`를 주면 첫 실행은 모델을 만들지 않고 질문만 뽑습니다.
LLM에 “매크로/코드 금지, Q1: … 형식으로 질문만”을 지시하고,
질문이 있으면 questions.txt + “RESULT: QUESTIONS PENDING
(ask-first …)”를, 질문이 없으면 “RESULT: ASK-FIRST NO QUESTIONS”를
남깁니다. freecadcmd 검사는 이 단계에서는 건너뜁니다 (만드는 게
없으니까). 답은 웹 UI 계속 작업으로 `--text`에 넣어 다음 실행에서
만듭니다. 만드는 도중 새 질문이 생기면 그 실행도 QUESTIONS
PENDING이 되고, 답하면 다시 만듭니다.

## 질문과 임시 결과
- 매크로에 Q1~Q9 같은 질문이 있으면, `<output-dir>/questions.txt`로
  뽑히고 report.txt에도 적혀. 결과 페이지 QA 탭에서 바로 보여.
- 질문이 있는데도 솔리드가 만들어지면, 종료 코드는 0이지만 결과는
  성공이 아니야. report.txt에는 “RESULT: QUESTIONS PENDING”으로
  적히고, 결과 페이지 배너에도 “질문 대기 중 — 성공이 아닙니다”로
  뜬다. 임시값으로 만든 모델이니까, 답을 주고 다시 실행해.
- 안전 검사는 주석을 검사하지 않아. 주석에 “AttachmentOffset”이라고
  적혀 있다고 실행을 막지 않아. 코드로 실제로 쓰는 경우만 막아.

## 아직 안 되는 것
- .fcstd에서 2D 도면을 자동으로 뽑아내는 TechDraw는 아직 자동화가 안 됐어.
  지금은 FreeCAD GUI에서 TechDraw 페이지를 직접 만들어서 뷰를 뽑아.
- API를 호출하지 않고 프롬프트만 확인하고 싶으면 `--dry-run`을 붙여.
