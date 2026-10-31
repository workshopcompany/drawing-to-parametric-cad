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

## 모델링 생성완료 + 매칭표 (matching.json)
“성공”이라는 말은 쓰지 않습니다. 게이트는 STEP 솔리드 1개 +
유효 True뿐이고, 결과는 “RESULT: MODELING COMPLETE”입니다.
도면과 같다는 뜻이 아닙니다. 매칭표는 matching.json에 남고
report.txt에도 줄로 적힙니다. 도면값은 LLM이 도면에서 읽어
매크로에 쓴 값(질문 먼저 D치수, 확인된 답변 포함)이고, 모델링값은
매핑에서 읽습니다. 만드는 LLM이 매크로 맨 위에 적는 FEATURE_MAP이
치수마다 어느 피처·스케치·kind인지를 정하고, 파이프라인은 빌드 성공
후 mapping.json으로 저장해서 표를 만듭니다. kind는 pad_length,
diameter, radius, sketch_constraint(D-번호로 이름 붙인 구속),
feature_extent, span, chamfer_size 7종입니다. 매핑이 없는 행은
추측으로 채우지 않고 ?가 뜹니다. 매크로 글 뒤지기, 실린더 추측,
전체 길이 규칙은 폐기했습니다 (옛 폴더에서만 레거시 경로로 유지).
참조치수(도면에서 괄호 표시)는 "? (참조치수)"로 뜹니다. D치수는
질문 먼저부터 /answer를 거쳐 표까지 뷰 태그
([front]/[section]/[side]/[top])를 들고 갑니다.
O는 0.01mm 이내, X는 다름, ?는 이런 방식으로는 비교 불가,
? (참조치수)는 참조치수, ~는 참고용.
질문 먼저 단계에서는 D치수 목록을 dimensions.json에 저장하고,
위치가 있으면 drawing_numbered.png에 빨간 번호 배지를 찍습니다
(PIL이 없거나 위치가 없으면 생략, 위치는 추정치이며 측정 입력으로
쓰지 않습니다). 자세한 설계는 MAPPING_DESIGN.md를 보세요.

## design-question FAIL (매크로 없이 질문만 온 경우)
LLM이 매크로 대신 질문만 내놓으면 파이프라인은 자가수정하지
않고 guidance.txt에 질문 원문을 남긴 뒤 "RESULT: FAIL -
design question"으로 종료합니다 (종료 코드 1, 모델 없음).
질문도 questions.txt에 같이 남기므로 웹 UI에서 바로 계속
작업 폼이 뜹니다. 설계 질문은 절대 지어내서 우회하지 않습니다.

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
- questions.txt에는 열린 질문만 들어가. 이미 답했거나 확정됐거나
  built exact인 항목, 다른 질문을 가리키는 말(`see Q30`)은 질문에서
  빠져. LLM이 닫힌 항목을 Q-line으로 다시 적지 않도록 프롬프트에도
  규칙이 있어.
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

## 실측: --measure 모드

`python3 run_pipeline.py --measure --output-dir <결과 폴더>
--freecadcmd <경로>`는 이미 있는 결과 폴더의 model.step을 실측해서
matching.json에 실측값 칸을 추가해. 도면도 API도 다시 안 쓰고,
모델도 다시 안 만들어. freecadcmd로 measure_step.py를 돌려서 실제
형상을 재: 평행한 평면 사이 거리, 직선 엣지 길이(방향축 포함),
위상 버텍스 간 좌표 차이(메시 점이 아님), 수평 단면 크기(Z 25단면),
전체 bbox 크기, 실린더 지름.

매칭 규칙: 매핑이 있는 폴더는 앵커드 실측만 씁니다. 각 D행은 매핑된
피처의 STEP 면에서만 잽니다. 피처 생성 면을 STEP 면과 대조하고
(표면 종류·중심·면적, 트리 역순), 나중 피처에 잘리거나 합쳐진 면은
재배치로 찾습니다 (끝면 오프셋, 생성 반경, 스케치 프레임 bbox).
매핑이 없는 옛 폴더는 기존 배터리 폴백을 씁니다: 지름/반지름 행은
실린더만, 오프셋/위치/공차 행은 실측 안 해(위치지 크기 아님).
나머지 크기 행은 배터리에서 골라. 뷰로 축이 정해지는 행(정면/측면/
평면, 깊이/두께 단어)은 그 축 또는 각진 것(angled)만 받아, 다른
축은 아예 제외해. 실린더 지름도 다른 크기 행과 근접도로 경쟁해
(밴드 0.05, 축 없음, 지름만). 둥근 피처의 폭은 곧 지름이거든.
이게 없으면 16 스텝이 축 길이 14.5를, 10 보스가 탭 위치 9.5를
집어왔어. 밴드: 축에 맞은 면/단면/bbox 값은 max(0.1, 값의 10%),
정확하거나 빽빽한 값(엣지, 버텍스 차이, 각진 면쌍)은 0.05야.
빽빽한 풀은 느슨한 밴드에서 우연을 "찾아내"거든(뾰족점-슬롯끝
차이가 팁 높이인 척). 실측값에는 판정이 없어. 도면값이랑 직접
비교해(일반 공차 ±0.1, 표의 엄격 0.01 아님).
방법(예: "Pad_Step cylinder diameter")은 행마다 저장되고 마우스
올리면 보여. 모델링 방법도 모델링값 셀에 마우스를 올리면 보여.

v1에서 솔직하게 비워두는 경우(—로 표시, 지어내지 않음): 매핑이
없거나, 피처를 찾을 수 없거나, kind를 읽을 수 없는 행. 모서리
점이 없는 매끈한 곡선 꼭대기는 버텍스로 재지 않아. 메시 점은
일부러 안 써. 메시 점은 거의 모든 값 근처에 있어서 뭐든
"확인"해버리거든. 단, 훅 팁 같은 곡선 국소 최소값은 스팬
localmin 모드로 잰다 (곡선 순서 샘플링의 내부 극소값).
파일: measurements.json(+ measured_at),
measure_log.txt, matching.json에 D행마다 measured/measured_method
추가, report.txt에 요약 한 줄 추가.
참고: macro.py가 남아 있는 폴더는 --measure가 모델링값/결과 칸도
최신 매칭 규칙으로 다시 계산해. 옛날 결과 폴더는 전체 bbox 매핑
(폭 -> Y 크기, 높이 -> Z 크기)이라 실측값은 거의 맞는데도 X가 뜬
행이 있어. 다시 실측하면 그 행들이 최신 규칙으로 O나 ?가 돼.
macro.py가 없는 폴더는 예전 행을 유지하고, 검증 실패가 좋은 행을
?로 떨어뜨리지는 않아.
--measure는 D행마다 실측 판정(measured_result)도 써. 실측값이 도면값
±0.1(일반 공차) 안에 있으면 O, 더 벌어지면 X, 실측이 없으면 ?야.
표의 엄격 0.01이 아닌 이유는, 받아들인 윤곽 편차(뾰족 높이 1.739 대
1.70)까지 X로 뜨면 안 되기 때문이야. 웹 UI에서는 모델링 기반 Result와
별도로 Measured 옆에 "실측 판정" 칸으로 보여.

## questions.txt 계약 (2026-10-30, 질문창 매크로 덤프 방지)
- questions.txt는 `write_questions()`로만 쓰고, 검증된 `Q숫자:` 줄만 들어간다. 코드, 일반 글, 응답 전체는 절대 여기에 쓰지 않는다 (raw_response.txt / guidance.txt에 남는다).
- fence 없는 매크로도 코드로 취급한다: `looks_like_question()`은 FreeCAD 코드 흔적이 있으면 질문이 아니라고 판단하고, `extract_macro()`는 fence 없는 코드도 매크로로 추출한다. 예전에는 fence 없는 매크로가 `QUESTION:` 로그 문자열과 `?` 때문에 디자인 질문으로 오판돼 전체가 questions.txt에 들어갔다.
- 새 실행 시작 때 questions.txt를 지우고, 질문 없는 최종 시도는 이전 시도의 questions.txt를 삭제한다. 오래된 파일이 배너를 끌고 다니지 않는다.

## 특징 검사 (--inspect, 실패 게이트 아님)
- 기존 결과 폴더를 다시 만들지 않고 검사만 한다: 현재 .fcstd + STEP을 새로 검증하고, 매칭표 + FEATURE_MAP과 대조해 feature_check.txt/.json을 쓰고, feature_check_history.txt에 한 줄 요약(OK/MISS/DIFF/?/REF + 빠진 목록)을 추가한다.
- 검사가 빠짐을 찾아도 종료 코드는 0이고, 모델/매크로/report.txt는 바꾸지 않는다. 빠짐은 "다음 Continue에서 고칠 목록"이지 "실패해서 버릴 모델"이 아니다.
- MISS는 모델링값이 없거나 .fcstd에 특징이 없는 경우, DIFF는 값은 있는데 도면값과 다른 경우(도면 오독일 수도 있음), REF는 공차/일반 챔퍼 같은 비형상 행이다.
