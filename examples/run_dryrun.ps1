param(
    [Parameter(Mandatory = $true)]
    [string]$DatasetRoot,
    [Parameter(Mandatory = $true)]
    [string]$ModelsJson,
    [string]$OutputRoot = "outputs\dryrun"
)

yolo-label-recovery run `
  --dataset-root $DatasetRoot `
  --out-root $OutputRoot `
  --models-json $ModelsJson `
  --classes person helmet vest tractor slipper smoking `
  --splits train val test `
  --imgsz 832 `
  --batch 32 `
  --device 0 `
  --workers 0 `
  --draw-review `
  --draw-auto-samples 80 `
  --dry-run `
  --force
