import React, { useRef } from 'react';
import { Cloud, ArrowRight, Activity, Database, CloudRain, Wind, Droplets, Thermometer, AlertTriangle, FileText } from 'lucide-react';
import { motion, useScroll, useTransform } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { LiquidButton } from '../components/ui/liquid-glass-button';
import { SquircleCard } from '../components/ui/squircle';
import { Carousel3D } from '../components/ui/carousel-3d';

const Home = () => {
  const navigate = useNavigate();

  // Cloud configuration for animation
  const clouds = [
    { top: '10%', duration: '45s', size: 'w-24 h-24', opacity: 'opacity-70', delay: '0s' },
    { top: '25%', duration: '35s', size: 'w-32 h-32', opacity: 'opacity-90', delay: '-10s' },
    { top: '45%', duration: '55s', size: 'w-20 h-20', opacity: 'opacity-60', delay: '-25s' },
    { top: '65%', duration: '40s', size: 'w-40 h-40', opacity: 'opacity-80', delay: '-5s' },
    { top: '80%', duration: '60s', size: 'w-16 h-16', opacity: 'opacity-50', delay: '-30s' },
  ];


  const { scrollYProgress } = useScroll();
  const y1 = useTransform(scrollYProgress, [0, 1], [0, -400]);
  const y2 = useTransform(scrollYProgress, [0, 1], [0, -200]);
  const y3 = useTransform(scrollYProgress, [0, 1], [0, -600]);
  const y4 = useTransform(scrollYProgress, [0, 1], [0, -300]);
  const y5 = useTransform(scrollYProgress, [0, 1], [0, -500]);
  const parallaxTransforms = [y1, y2, y3, y4, y5];

  const widgets = [
    {
      id: 'aqi',
      label: 'Air Quality',
      title: 'AQI Dashboard',
      description: 'Real-time air quality index, pollutant tracking, and health recommendations.',
      icon: Wind
    },
    {
      id: 'wqi',
      label: 'Water Quality',
      title: 'WQI Analytics',
      description: 'Comprehensive water quality metrics including pH, turbidity, and dissolved oxygen.',
      icon: Droplets
    },
    {
      id: 'temp',
      label: 'Climate',
      title: 'Temperature Patterns',
      description: 'Global and localized temperature tracking with historical comparison models.',
      icon: Thermometer
    },
    {
      id: 'rain',
      label: 'Weather',
      title: 'Rainfall Forecast',
      description: 'Advanced precipitation forecasting and drought indicator mapping.',
      icon: CloudRain
    },
    {
      id: 'anomalies',
      label: 'Alerts',
      title: 'Anomaly Detection',
      description: 'AI-driven detection of environmental anomalies and early warning systems.',
      icon: AlertTriangle
    },
    {
      id: 'reports',
      label: 'Data',
      title: 'Automated Reports',
      description: 'Generate compliance-ready environmental impact and sustainability reports.',
      icon: FileText
    }
  ];

  return (
    <div className="w-full min-h-screen pb-20 animate-fade-in transition-colors duration-500">
      
      {/* Hero Section */}
      <div className="relative w-full h-[80vh] rounded-3xl overflow-hidden shadow-xl border border-white/40 bg-gradient-to-b from-sky-400 via-sky-300 to-sky-100 mb-12 transition-colors duration-500">
        
        {/* Premium Background Dot Grid */}
      <div className="absolute inset-0 bg-dot-pattern opacity-60 mix-blend-overlay z-0 pointer-events-none"></div>

      {/* Animated Background Items (Clouds) */}
      {clouds.map((item, index) => (
        <motion.div 
          key={`cloud-${index}`} 
          className="absolute animate-cloud"
          style={{ 
            top: item.top, 
            animationDuration: item.duration,
            animationDelay: item.delay,
            y: parallaxTransforms[index % parallaxTransforms.length]
          }}
        >
          <Cloud 
            className={`text-white fill-white ${item.size} ${item.opacity} drop-shadow-md`} 
            strokeWidth={1}
          />
        </motion.div>
      ))}

      {/* Hero Content Overlay */}
      <div className="relative z-10 h-full flex flex-col items-center justify-center px-4 text-center">
        <SquircleCard 
          cornerRadius={40}
          squircleClassName="glass-panel p-10 md:p-16 max-w-3xl w-full mx-auto backdrop-blur-xl bg-white/30 border-white/50 transition-colors duration-500"
          className="max-w-3xl w-full"
        >
          <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full glass-card text-blue-800 font-medium text-sm mb-6 transition-colors duration-500">
            <Activity className="w-4 h-4" />
            <span>Real-time Environmental Monitoring</span>
          </div>
          
          <h1 className="text-4xl md:text-6xl font-extrabold text-slate-800 tracking-tight mb-6 drop-shadow-sm transition-colors duration-500">
            Analyze. Predict. <span className="text-blue-600">Protect.</span>
          </h1>
          
          <p className="text-lg md:text-xl text-slate-700 mb-10 max-w-2xl mx-auto leading-relaxed transition-colors duration-500">
            The ultimate cloud-based platform for integrating and managing environmental data. Monitor air, water, and climate parameters seamlessly.
          </p>

          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <LiquidButton 
              onClick={() => navigate('/upload')}
              size="xxl"
              className="w-full sm:w-auto bg-white/80 hover:bg-white text-blue-800 border border-sky-200 transition-colors duration-500"
            >
              <Database className="w-5 h-5" />
              Upload Data
            </LiquidButton>
            <LiquidButton 
              onClick={() => navigate('/aqi')}
              size="xxl"
              className="w-full sm:w-auto bg-blue-600 hover:bg-blue-700 text-white shadow-lg hover:shadow-blue-500/30 transition-colors duration-500"
            >
              <CloudRain className="w-5 h-5" />
              View Dashboards
              <ArrowRight className="w-5 h-5" />
            </LiquidButton>
          </div>
        </SquircleCard>
      </div>
      </div>

      {/* Widgets Section */}
      <div className="w-full py-12 relative z-10">
        <div className="text-center mb-8 px-4">
          <h2 className="text-3xl md:text-5xl font-extrabold text-slate-800 tracking-tight mb-4 drop-shadow-sm transition-colors duration-500">
            Platform <span className="text-blue-600">Features</span>
          </h2>
          <p className="text-slate-600 max-w-2xl mx-auto text-lg transition-colors duration-500">
            Explore our comprehensive suite of environmental monitoring tools and analytics dashboards.
          </p>
        </div>
        <Carousel3D items={widgets} />
      </div>
    </div>
  );
};

export default Home;
