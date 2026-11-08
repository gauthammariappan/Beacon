# Creating the training dataset (3 mics, 5 boxes, 10 cm wide, side by side)

**Total time:** about 30 minutes. That's two sessions of about 10 minutes each, plus a 10–15 minute break.
**Result:** 12 files, about 400 labeled beeps plus non-beep sounds.

---

## The layout (seen from above, turret at the bottom)

```
   ┌────┬────┬────┬────┬────┐
   │ A  │ B  │ C  │ D  │ E  │     5 boxes, ~10 cm wide, touching (0–3 mm gaps)
   └─▽──┴─▽──┴─▽──┴─▽──┴─▽──┘     openings face the turret; row is ~50 cm long
     🎤L       🎤M       🎤R        mics ~5 cm in front of A, C and E
            [Pico]                 just behind mic M
              ▲
          [turret]                 ~30–40 cm back, centered on box C
```

Because the boxes touch, neighboring boxes are only **10 cm** apart. That's why the mics sit **close** to the boxes, about **5 cm** out. Closer mics make neighboring boxes sound more different: about 7 dB apart at 5 cm, compared with about 4 dB at 10 cm.

---

## Part 1: Get the beep sound onto the phone (5 min)

1. On the laptop, open Finder → **Desktop → beacon → beeps**.
2. The file to use is **`beacon_P1_on_battery.wav`**.
   - It's 3 minutes long: 4 short beeps (2500 Hz, 0.15 s each), then a **4-second pause**, repeating.
   - It's the same sound as the demo.
3. Send it to the beeper phone:
   - **iPhone:** right-click the file → **Share → AirDrop** → your phone. It lands in the **Files** app.
   - **Android:** send it with Quick Share, Google Drive or email.
4. Set up the beeper phone:
   - **Volume at max.** Press volume-up while the file is playing.
   - **Silent mode off.**
   - **Do Not Disturb on**, so notification sounds don't get recorded.
   - **Auto-Lock: Never** (Settings → Display & Brightness), so playback doesn't stop.
   - Use the **phone's own speaker**, never Bluetooth.
   - Use **this same phone for the demo.**

## Part 2: Lock down the layout (10–15 min, before any recording)

1. **Boxes:**
   - Line up the 5 boxes in a straight row, touching, openings facing the turret.
   - Label them **A B C D E, left to right as seen from the turret**, in big letters on the top or above each opening.
2. **Mics:**
   - **L** in front of the **middle of box A**, **M** in front of the **middle of box C**, **R** in front of the **middle of box E**.
   - Each about **5 cm** from the box front, at opening height, facing the box.
   - Keep each mic **low**, at the bottom edge of the opening, so the laser can hit the **upper part** of the box face above it.
3. **Pico:** just behind mic M, in the middle. The row is only 50 cm, so normal jumpers may reach mics L and R. Only add M-F extensions if a wire is short.
4. **Turret:** about **30–40 cm** back from box C, centered on it.
5. **Tape everything down:** boxes, mic arms, wires, Pico, turret. Draw tape outlines around each one.
6. **From now on, nobody touches the blue knobs on the mics.**
7. **Background phone (a second phone):** AirDrop it **`beacon_background_chatter.wav`** (15 minutes of people talking over each other). Put it in one fixed spot (for example behind the turret), volume about halfway, and **press play before the first box. It plays the whole time:** during the beeping, during the NONE recording, in both sessions and in the demo. The rule is: same conditions in recording and in the demo.

## Part 3: Who does what (2–3 people)

| Job | Does |
|---|---|
| **Operator** (at the laptop) | Types the commands and reads out the numbers |
| **Phone mover** | Puts the phone in the right box and moves it between bursts |
| **Noise maker** | Makes the non-beep sounds and keeps people from standing between the boxes and the mics |

## Part 4: Open the terminal (1 min)

1. On the laptop, press **Cmd+Space**, type **Terminal** and press Enter.
2. Type `cd ~/Desktop/beacon` and press Enter.
3. On the phone: Files app → Browse → **Downloads** → tap **beacon_P1_on_battery.wav**. A player opens. Don't press play yet.

## Part 5: Session 1 (about 10 min), guided by the laptop

1. **Operator** types this once:
   ```
   python3 tools/record.py --session 1
   ```
2. It says **`NEXT: BOX A ... Press Enter when ready`**. The phone mover holds the phone at **box A's opening** with the player open, **not playing**. Operator presses **Enter**.
3. **Everyone stays quiet for about a second.** It's learning the room's background.
4. It says **`READY. Press PLAY now, slide the phone into box A, spot 1`**. The phone mover presses **play once**, slides the phone in and takes the hand out. **The audio keeps playing the whole time; never press play again for this box.**
5. The phone plays 4 beeps. The laptop prints `beep 1/40` … `beep 4/40`, then:
   **`>> MOVE the phone (still box A) to spot 2: pushed to the back`**
   During the 4-second silence, move the phone to that spot **inside box A**, then take your hand out.
6. That repeats for **10 spots** (40 beeps, about 55 seconds). **The phone stays in box A the whole time.**
7. It says **`Box A done. PAUSE the phone.`** Pause it.
8. It immediately says **`NEXT: BOX B`**. Same thing for box B (10 spots inside box B), then C, D and E.
9. Last it says **`NEXT: NONE`**. **Pause and put away the beeper phone**, press Enter, then for 60 seconds clap, talk, laugh and tap the table near every box. No beeps.
10. It says **`Session 1 done!`**.

**Check the numbers as you go:**

| Box | You should usually see |
|---|---|
| A | **L** clearly loudest |
| B | **L and M** close, R quiet |
| C | **M** clearly loudest |
| D | **M and R** close, L quiet |
| E | **R** clearly loudest |

If a box looks clearly wrong, or it says only N/40 beeps were heard, type **`r`** and press Enter to redo that box.

**Redo just one box later:** `python3 tools/record.py --session 1 --label C`.

## Part 6: Break (10–15 min)
**Don't move anything.** Leave the background chatter playing (or pause it, but press play again before session 2, same spot and volume).

## Part 7: Session 2 (about 10 min, the honest test)
Run `python3 tools/record.py --session 2` and do exactly the same. This time, put the phone in the spots in a **different order** and try in-between spots. If possible, a different person moves the phone.

## Part 8: Check you have all 12 files
Type `ls data/recordings`. You should see:
```
session1_A.csv  session1_B.csv  session1_C.csv  session1_D.csv  session1_E.csv  session1_NONE.csv
session2_A.csv  session2_B.csv  session2_C.csv  session2_D.csv  session2_E.csv  session2_NONE.csv
```
Then tell Claude **"recorded"**. Claude runs `python3 tools/train.py`, which:
- trains on session 1 and tests on session 2;
- compares the two baselines (loudest mic, weighted centroid) with kNN and a random forest;
- shows the accuracy, which boxes get confused, and the accuracy with 4-beep voting;
- saves the best model for the live demo.

If neighboring boxes get confused a lot, record a **session 3** the same way. More varied data is the first fix.

---

## The laser, for later

With 10 cm boxes about 35 cm from the turret, neighboring boxes are only about **15° apart**. With your saved center of **68°**, expect roughly:
- **C ≈ 68°**
- **B and D ≈ 68 ± 15°**
- **A and E ≈ 68 ± 30°**

Which side is which depends on how the servo is mounted. Calibrate each box with `AIM,<angle>` and `POS?`.

## Rules
- **The letter you type must match the box the phone is in.** One recording = one box.
- **Stay out of the space between the boxes and the mics** while recording. Bodies block and reflect sound.
- **If anything moves** (a mic, a box), re-record **both** sessions. The model learns the layout you recorded in.
- **If only the turret moves**, just recalibrate the laser angles. No re-recording.

## If something goes wrong

| You see | Do this |
|---|---|
| `Can't find the Pico` | Push the USB cable back in (and the adapter into the Mac). |
| `Lost the Pico mid-recording` | Push the cable back in. Delete the partial file it names, then record that box again. |
| `No mic data yet` | The Pico is running an old sketch. Ask Claude to re-upload the turret firmware. |
| `Only N/40 beeps were heard` | Volume to max, speaker toward the opening, then run it again. It saves as `_2` and never overwrites. |
| You recorded the wrong box | Delete that file from `data/recordings/` and record it again. |
| A notification or ringtone went off during a box | Delete that box's file and record it again. |
