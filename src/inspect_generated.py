import subprocess, os, glob

for kfile in sorted(glob.glob("Generated_Reports/*.key")):
    script = """
    tell application "Keynote"
        set myDoc to open POSIX file "{path}"
        set sCount to count of slides of myDoc
        set res to ""
        repeat with s from 1 to sCount
            tell slide s of myDoc
                set tiCount to count of text items
                repeat with i from 1 to tiCount
                    set t to object text of text item i
                    if t contains "breakdown" then
                        set res to res & "Slide " & (s as string) & " item " & (i as string) & ": " & t & return
                    end if
                end repeat
            end tell
        end repeat
        close myDoc saving no
        return res
    end tell
    """.replace("{path}", os.path.abspath(kfile))

    proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    print("FILE:", kfile)
    print(proc.stdout)
