import subprocess, os

script = """
tell application "Keynote"
    set myDoc to open POSIX file "{path}"
    tell slide 1 of myDoc
        set tiCount to count of text items
        set res to ""
        repeat with i from 1 to tiCount
            set t to object text of text item i
            set res to res & (i as string) & ": " & t & return
        end repeat
    end tell
    close myDoc saving no
    return res
end tell
""".replace("{path}", os.path.abspath("Sample output/Sample-keynote1.key"))

proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
print("STDOUT:\n", proc.stdout)
print("STDERR:\n", proc.stderr)
