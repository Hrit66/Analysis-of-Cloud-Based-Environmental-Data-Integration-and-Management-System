import React, { useRef, useState, useEffect } from "react";
import { motion } from "framer-motion";
import { useLocation, useNavigate } from "react-router-dom";

export const SlideTabs = ({ tabs = [] }) => {
  const [position, setPosition] = useState({
    left: 0,
    width: 0,
    opacity: 0,
  });
  const tabsRef = useRef([]);
  const location = useLocation();

  // Find index of currently active tab based on route
  const activeIndex = tabs.findIndex(t => t.path === location.pathname);
  const selected = activeIndex >= 0 ? activeIndex : 0;

  useEffect(() => {
    const selectedTab = tabsRef.current[selected];
    if (selectedTab) {
      const { width } = selectedTab.getBoundingClientRect();
      setPosition({
        left: selectedTab.offsetLeft,
        width,
        opacity: 1,
      });
    }
  }, [selected, tabs.length]);

  return (
    <ul
      onMouseLeave={() => {
        const selectedTab = tabsRef.current[selected];
        if (selectedTab) {
            const { width } = selectedTab.getBoundingClientRect();
            setPosition({
                left: selectedTab.offsetLeft,
                width,
                opacity: 1,
            });
        }
      }}
      className="relative mx-auto flex w-fit rounded-full border-2 border-white/60 bg-white/40 backdrop-blur-md p-1 shadow-sm shrink-0"
    >
      {tabs.map((tab, i) => (
         <Tab
            key={tab.path}
            ref={(el) => (tabsRef.current[i] = el)}
            setPosition={setPosition}
            tab={tab}
            isActive={selected === i}
          />
      ))}

      <Cursor position={position} />
    </ul>
  );
};

const Tab = React.forwardRef(({ tab, setPosition, isActive }, ref) => {
  const navigate = useNavigate();

  return (
    <li
      ref={ref}
      onClick={() => navigate(tab.path)}
      onMouseEnter={() => {
        if (!ref?.current) return;
        const { width } = ref.current.getBoundingClientRect();
        setPosition({
          left: ref.current.offsetLeft,
          width,
          opacity: 1,
        });
      }}
      className={`relative z-10 flex cursor-pointer items-center gap-1.5 px-3 py-1.5 text-sm md:px-4 md:py-2 transition-colors duration-300
        ${isActive ? 'text-slate-900 font-medium' : 'text-slate-600 hover:text-slate-900'}
      `}
    >
      {tab.icon && <tab.icon className={`w-4 h-4 transition-colors duration-300 ${isActive ? tab.color : 'text-slate-500 group-hover:text-slate-700'}`} />}
      <span className="hidden xl:inline-block">{tab.name}</span>
    </li>
  );
});

const Cursor = ({ position }) => {
  return (
    <motion.li
      animate={{
        ...position,
      }}
      className="absolute z-0 h-8 md:h-9 rounded-full bg-white shadow-sm"
    />
  );
};
