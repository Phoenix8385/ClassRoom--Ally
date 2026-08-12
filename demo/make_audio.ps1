# Regenerate demo/demo_speech.wav using the text-to-speech voice built into
# Windows. Produces 16 kHz mono 16-bit PCM, which is exactly the format the
# WebSocket pipeline expects, so no ffmpeg or conversion step is needed.
#
#   powershell -File demo/make_audio.ps1
#   powershell -File demo/make_audio.ps1 -Sentences "Hello students","Sit down"

param(
    [string[]] $Sentences = @(
        "Good morning students.",
        "Open your books to page five.",
        "I am not going to class today."
    ),
    [string] $OutFile = "$PSScriptRoot\demo_speech.wav"
)

Add-Type -AssemblyName System.Speech

$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(
    16000,
    [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
    [System.Speech.AudioFormat.AudioChannel]::Mono
)
$synth.SetOutputToWaveFile($OutFile, $format)

# Slower than default: the 1-second analysis windows resolve clearer speech
# better, and it leaves the CPU room to keep up with the stream.
$synth.Rate = -2

$builder = New-Object System.Speech.Synthesis.PromptBuilder
foreach ($line in $Sentences) {
    $builder.AppendText($line)
    # A long gap so the 0.6 s silence timeout fires and each sentence is
    # finalised on its own instead of running into the next one.
    1..4 | ForEach-Object {
        $builder.AppendBreak([System.Speech.Synthesis.PromptBreak]::ExtraLarge)
    }
}

$synth.Speak($builder)
$synth.Dispose()

$bytes = (Get-Item $OutFile).Length
"{0}  ->  {1:N1} seconds, {2} sentences, 16 kHz mono PCM" -f `
    $OutFile, (($bytes - 44) / 32000), $Sentences.Count
