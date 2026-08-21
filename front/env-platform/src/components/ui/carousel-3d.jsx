import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { cn } from '../../lib/utils';
import { SquircleCard } from './squircle';

export const Carousel3D = ({ items = [] }) => {
  const [activeIndex, setActiveIndex] = useState(0);

  const handleNext = () => {
    setActiveIndex((prev) => (prev + 1) % items.length);
  };

  const handlePrev = () => {
    setActiveIndex((prev) => (prev - 1 + items.length) % items.length);
  };

  if (!items.length) return null;

  return (
    <div className="relative w-full max-w-5xl mx-auto flex flex-col items-center justify-center py-20 px-4">
      {/* 3D Stack Area */}
      <div className="relative w-full h-[400px] flex items-center justify-center perspective-[1000px] transform-style-3d">
        <AnimatePresence initial={false}>
          {items.map((item, index) => {
            // Calculate distance from active index, wrapping around
            const offset = (index - activeIndex + items.length) % items.length;
            const signedOffset = offset > Math.floor(items.length / 2) ? offset - items.length : offset;

            // Define animation properties based on offset
            const isActive = signedOffset === 0;
            const x = signedOffset * 180; // horizontal spacing
            const scale = isActive ? 1 : 1 - Math.abs(signedOffset) * 0.15;
            const zIndex = items.length - Math.abs(signedOffset);
            const opacity = isActive ? 1 : 1 - Math.abs(signedOffset) * 0.3;
            // Optionally, add a slight rotateY for a cover flow effect
            const rotateY = signedOffset * -15;

            // Don't render items that are too far away to improve performance
            if (Math.abs(signedOffset) > 2) return null;

            return (
              <motion.div
                key={item.id}
                initial={{ opacity: 0, scale: 0.8, x: x + (signedOffset > 0 ? 100 : -100) }}
                animate={{ opacity, scale, x, zIndex, rotateY }}
                transition={{ type: "spring", stiffness: 260, damping: 20 }}
                className={cn(
                  "absolute top-1/2 left-1/2 -mt-[160px] -ml-[140px] w-[280px] h-[320px] transition-all duration-300",
                  isActive ? "cursor-pointer" : "pointer-events-none"
                )}
                style={{ transformOrigin: "center center" }}
              >
                {/* The glass card */}
                <SquircleCard
                  cornerRadius={36}
                  className="w-full h-full drop-shadow-xl"
                  squircleClassName="w-full h-full bg-white border border-slate-100 shadow-xl p-6 flex flex-col items-center justify-center text-center relative group"
                >
                  {/* Glowing background blob */}
                  <div className="absolute inset-0 bg-gradient-to-br from-sky-50 to-blue-50/50 opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none"></div>
                  
                  {item.icon && (
                    <div className="w-16 h-16 rounded-full bg-blue-100/50 flex items-center justify-center mb-6 shadow-sm border border-white/60 group-hover:scale-110 group-hover:shadow-md transition-all duration-500">
                      <item.icon className="w-8 h-8 text-blue-600 drop-shadow-sm transition-transform group-hover:scale-105" />
                    </div>
                  )}
                  
                  {item.label && (
                    <span className="px-3 py-1 bg-slate-100 text-blue-800 text-xs font-bold tracking-wider rounded-full uppercase mb-4 shadow-sm border border-slate-200">
                      {item.label}
                    </span>
                  )}
                  
                  <h3 className="text-xl font-extrabold text-slate-800 mb-3 drop-shadow-sm leading-tight px-2">
                    {item.title}
                  </h3>
                  
                  <p className="text-sm text-slate-600 line-clamp-3 px-1 leading-relaxed">
                    {item.description}
                  </p>
                </SquircleCard>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>

      {/* Controls & Pagination */}
      <div className="mt-12 flex flex-col items-center gap-6">
        <div className="text-4xl font-black text-slate-800 tracking-tighter drop-shadow-sm flex items-baseline">
          {String(activeIndex + 1).padStart(2, '0')}
          <span className="text-lg font-semibold text-slate-500 ml-2 tracking-normal">of {String(items.length).padStart(2, '0')}</span>
        </div>

        <div className="flex items-center gap-6 bg-white/40 p-2 rounded-full border border-white/50 shadow-sm backdrop-blur-sm">
          <button
            onClick={handlePrev}
            className="w-10 h-10 rounded-full bg-white hover:bg-slate-50 flex items-center justify-center text-slate-600 hover:text-blue-600 hover:scale-105 transition-all border border-slate-200 shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-400/50"
            aria-label="Previous slide"
          >
            <ChevronLeft className="w-5 h-5 ml-[-2px]" />
          </button>

          <div className="flex gap-2 px-2">
            {items.map((_, idx) => (
              <button
                key={idx}
                onClick={() => setActiveIndex(idx)}
                className={cn(
                  "h-1.5 rounded-full transition-all duration-300",
                  idx === activeIndex ? "w-6 bg-blue-600 shadow-[0_0_8px_rgba(37,99,235,0.4)]" : "w-1.5 bg-slate-300 hover:bg-slate-400"
                )}
                aria-label={`Go to slide ${idx + 1}`}
              />
            ))}
          </div>

          <button
            onClick={handleNext}
            className="w-10 h-10 rounded-full bg-white hover:bg-slate-50 flex items-center justify-center text-slate-600 hover:text-blue-600 hover:scale-105 transition-all border border-slate-200 shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-400/50"
            aria-label="Next slide"
          >
            <ChevronRight className="w-5 h-5 mr-[-2px]" />
          </button>
        </div>
      </div>
    </div>
  );
};
