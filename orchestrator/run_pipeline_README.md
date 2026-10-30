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

## 아직 안 되는 것
- .fcstd에서 2D 도면을 자동으로 뽑아내는 TechDraw는 아직 자동화가 안 됐어.
  지금은 FreeCAD GUI에서 TechDraw 페이지를 직접 만들어서 뷰를 뽑아.
- API를 호출하지 않고 프롬프트만 확인하고 싶으면 `--dry-run`을 붙여.
