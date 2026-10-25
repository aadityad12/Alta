// B · At the bench (#28, #29): live camera with ALTA's highlights, the guide card (setup question or
// schematic + the current step) and the chat dock.

import { useState, type ComponentProps, type MutableRefObject, type ReactNode } from 'react'
import { BoardOverlay, type Calibration, type OverlayItem } from '../board'
import { labTitle } from '../app/labs'
import type { Lab } from '../app/protocol'
import { FIT, type CameraStatus, type Source } from '../app/useCamera'
import dotLive from '../assets/figma/dot-live.svg'
import userRound from '../assets/figma/user-round-blue.svg'
import { ChatDock } from '../ui/Chat'
import { FitSchematic, GuideDots, Header, StepNav, type NavState, type SchematicStep } from '../ui/kit'
import { CameraFrame } from './Camera'
import './screens.css'

const SETUP_CHECKS = ['Red pod wire in the + rail next to column a', 'Black pod wire in the − rail next to it', 'Phone on the stand, looking straight down']

type Props = {
  lab: Lab
  headerRight: ReactNode
  cam: { source: Source | null; stream: MediaStream | null; status: CameraStatus; retry: () => void }
  mediaRef: MutableRefObject<HTMLVideoElement | null>
  calibration: Calibration | null
  overlay: OverlayItem[]
  banner: ReactNode
  reading: ReactNode
  guide: { step: number; total: number; title: string; text: string; nav: NavState; onBack: () => void; onNext: () => void }
  dock: ComponentProps<typeof ChatDock>
}

export function Bench({ lab, headerRight, cam, mediaRef, calibration, overlay, banner, reading, guide, dock }: Props) {
  const setup = guide.step === 0
  const schematicStep: SchematicStep = guide.step >= 1 && guide.step <= 4 ? (guide.step as SchematicStep) : 'done'
  return (
    <div className="screen bench">
      <Header title={labTitle(lab.title)}>{headerRight}</Header>
      <div className="bench-body">
        <section className="cam-col">
          <div className="col-label">
            <img src={dotLive} width={10} height={10} alt="" />
            <h2 className="t-h3">Live camera</h2>
          </div>
          <CameraFrame
            source={cam.source}
            stream={cam.stream}
            status={cam.status}
            mediaRef={mediaRef}
            onRetry={cam.retry}
            extra={
              <>
                {banner && <div className="cam-banner">{banner}</div>}
                {reading && <div className="cam-reading">{reading}</div>}
              </>
            }
          >
            {({ w, h }) => <BoardOverlay items={overlay} calibration={calibration} lab={lab} videoW={w} videoH={h} fit={FIT} />}
          </CameraFrame>
        </section>

        <section className="guide-col">
          <div className="col-label">
            <h2 className="t-h3">Guide</h2>
            <span className="spacer" />
            <GuideDots total={guide.total + 1} current={guide.step + 1} />
          </div>
          <div className="guide-card">
            {setup ? (
              <SetupQuestion />
            ) : (
              <div className="guide-vis">
                <FitSchematic fill labId={lab.id} step={schematicStep} max={0.95} fallbackUrl={lab.schematic_url} />
              </div>
            )}
            <div className="guide-step">
              <span className="t-label c-blue">{setup ? 'Setup' : `Step ${guide.step} of ${guide.total}`}</span>
              <h3 className="t-h2">{guide.title}</h3>
              {guide.text && <p className="t-body-l c-60">{guide.text}</p>}
              <span className="gap-8" />
              <StepNav state={guide.nav} onBack={guide.onBack} onNext={guide.onNext} />
            </div>
          </div>
        </section>
      </div>
      <ChatDock {...dock} />
    </div>
  )
}

function SetupQuestion() {
  const [done, setDone] = useState<boolean[]>(SETUP_CHECKS.map(() => false))
  return (
    <div className="setup-q">
      <img src={userRound} width={30} height={30} alt="" />
      <p className="t-h2">Have you finished setting up the pod?</p>
      {SETUP_CHECKS.map((c, i) => (
        <label key={c} className="setup-check">
          <input type="checkbox" checked={done[i]} onChange={() => setDone(done.map((d, j) => (j === i ? !d : d)))} />
          <span className="box" aria-hidden />
          <span className="t-body-l">{c}</span>
        </label>
      ))}
    </div>
  )
}
