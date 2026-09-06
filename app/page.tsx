import ChatWidget from "@/components/ChatWidget";

export default function Home() {
  return <main className="min-h-screen bg-gradient-to-b from-slate-50 to-slate-100 p-6"><div className="mx-auto max-w-4xl pt-16 text-center"><p className="text-sm font-semibold uppercase tracking-[0.2em] text-emerald-600">PrimeHubMaal</p><h1 className="mt-3 text-3xl font-bold text-slate-900 sm:text-5xl">Salaar support shell</h1><p className="mx-auto mt-4 max-w-xl text-slate-600">Phase 1 demo page. Use the help bubble in the bottom-right corner to start a guest conversation.</p></div><ChatWidget /></main>;
}
