import { Closing, HomeFooter } from "./closing";
import { Hero } from "./hero";
import { HomeNav } from "./home-nav";
import { MatchShowcase } from "./match-showcase";
import { PipelineOrbit } from "./pipeline-orbit";
import { HomeMotion } from "./primitives";
import { SafetyDiagram } from "./safety-diagram";
import { TrackingShowcase } from "./tracking-showcase";

export function HomePage() {
  return (
    <HomeMotion>
      <div className="home-fx relative min-h-svh bg-background text-text-1">
        <HomeNav />
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
