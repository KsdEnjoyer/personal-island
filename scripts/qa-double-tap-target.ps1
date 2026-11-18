param([Parameter(Mandatory=$true)][string]$Folder)
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$form=New-Object System.Windows.Forms.Form
$form.Text='Personal Island QA double tap'
$form.StartPosition='Manual'
$form.Location=New-Object System.Drawing.Point(80,230)
$form.Size=New-Object System.Drawing.Size(460,260)
$first=New-Object System.Windows.Forms.TextBox
$first.Multiline=$true
$first.Location=New-Object System.Drawing.Point(12,12)
$first.Size=New-Object System.Drawing.Size(410,90)
$second=New-Object System.Windows.Forms.TextBox
$second.Location=New-Object System.Drawing.Point(12,125)
$second.Size=New-Object System.Drawing.Size(410,28)
$form.Controls.AddRange(@($first,$second))
$timer=New-Object System.Windows.Forms.Timer
$timer.Interval=30
$timer.Add_Tick({
  $commandPath=Join-Path $Folder 'command.json'
  if(Test-Path -LiteralPath $commandPath) {
    try {
      $command=Get-Content -Raw -Encoding utf8 -LiteralPath $commandPath | ConvertFrom-Json
      Remove-Item -LiteralPath $commandPath
      switch($command.action) {
        'prepare' {
          $first.Text=$command.text
          $second.Text='second '
          $first.SelectionStart=$first.TextLength
          $second.SelectionStart=$second.TextLength
          $form.Activate();$first.Focus()
        }
        'focus-second' { $second.Focus() }
        'read' {
          $point=$first.PointToScreen((New-Object System.Drawing.Point(20,70)))
          @{first=$first.Text;second=$second.Text;x=$point.X;y=$point.Y} | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $Folder ('typed-'+$command.id+'.json'))
        }
        'stop' { $form.Close() }
      }
      @{id=$command.id} | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $Folder ('ack-'+$command.id+'.json'))
    } catch { $_.Exception.Message | Set-Content -Encoding utf8 (Join-Path $Folder 'target-error.txt') }
  }
})
$form.Add_Shown({$first.Focus();'ready' | Set-Content (Join-Path $Folder 'ready');$timer.Start()})
try { [System.Windows.Forms.Application]::Run($form) }
finally { $timer.Stop();$timer.Dispose();$form.Dispose() }
