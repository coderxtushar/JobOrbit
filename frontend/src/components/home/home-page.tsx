import { Closing, HomeFooter } from "./closing";
import { Hero } from "./hero";
import { HomeNav } from "./home-nav";
import { MatchShowcase } from "./match-showcase";
import { PipelineOrbit } from "./pipeline-orbit";
import { HomeMotion } from "./primitives";
import { SafetyDiagram } from "./safety-diagram";
import { TrackingShowcase } from "./tracking-showcase";

/** ``signInFirst``: a sign-in site and a signed-out visitor, so the nav offers "Sign in". */
export function HomePage({ signInFirst = false }: { signInFirst?: boolean }) {
  return (
    <HomeMotion>
      <div className="home-fx relative min-h-svh bg-background text-text-1">
        <HomeNav signInFirst={signInFirst} />
        <main id="main" className="overflow-x-clip">
          <Hero />
          <PipelineOrbit />
          <MatchShowcase />
          <SafetyDiagram />
          <TrackingShowcase />
          <Closing />
        </main>
        <HomeFooter />
      </div>
    </HomeMotion>
  );
}
