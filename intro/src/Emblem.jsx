// Hexagon badge with a line icon per mission. The lines draw themselves in (pathLength) whenever the
// badge appears, and the ring turns slowly. Pure SVG + Framer Motion, no image files.
import { motion } from 'framer-motion';

const ICONS = {
  mountain: ['M10 46 L24 24 L31 33 L40 18 L54 46 Z', 'M36 24 L40 18 L44 24', 'M14 52 Q32 46 50 52'],
  city: ['M12 50 V30 H20 V50', 'M22 50 V18 H32 V50', 'M34 50 V26 H42 V50', 'M44 50 V34 H52 V50', 'M10 50 H54', 'M25 24 H29 M25 30 H29 M25 36 H29'],
  ship: ['M12 40 H52 L46 48 H18 Z', 'M22 40 V30 H36 V40', 'M29 30 V20', 'M29 20 L36 24', 'M8 54 Q16 50 24 54 T40 54 T56 54'],
  tree: ['M32 12 L20 30 H26 L16 44 H48 L38 30 H44 Z', 'M32 44 V54', 'M10 54 H54'],
  plane: ['M32 10 L35 26 L54 34 V38 L35 34 L34 46 L40 50 V53 L32 51 L24 53 V50 L30 46 L29 34 L10 38 V34 L29 26 Z'],
  tent: ['M10 50 L32 16 L54 50 Z', 'M32 16 V50', 'M26 50 L32 38 L38 50', 'M8 50 H56'],
  drone: ['M24 30 H40 V36 H24 Z', 'M24 30 L14 22 M40 30 L50 22 M24 36 L14 44 M40 36 L50 44', 'M8 22 H20 M44 22 H56 M8 44 H20 M44 44 H56', 'M32 36 V42 L28 48 H36 L32 42'],
  radar: ['M32 12 A20 20 0 1 1 31.9 12', 'M32 20 A12 12 0 1 1 31.9 20', 'M32 32 L46 18', 'M32 8 V14 M32 50 V56 M8 32 H14 M50 32 H56'],
};

const HEX = 'M32 2 L58 17 V47 L32 62 L6 47 V17 Z';

export default function Emblem({ kind, accent, size = 120, active = true, onClick, title }) {
  const paths = ICONS[kind] || ICONS.radar;
  return (
    <motion.button className="emblem" onClick={onClick} title={title} aria-label={title}
      style={{ width: size, height: size, '--accent': accent }}
      whileHover={{ scale: 1.08 }} whileTap={{ scale: 0.94 }}>
      <svg viewBox="0 0 64 64" width={size} height={size}>
        <motion.path d={HEX} fill="rgba(5,10,20,0.55)" stroke={accent} strokeWidth="1.6"
          initial={{ pathLength: 0 }} animate={{ pathLength: active ? 1 : 0.999 }} transition={{ duration: 1.1, ease: 'easeInOut' }} />
        <motion.g style={{ originX: '32px', originY: '32px' }} animate={{ rotate: 360 }} transition={{ duration: 40, repeat: Infinity, ease: 'linear' }}>
          <path d="M32 6 A26 26 0 0 1 58 32" fill="none" stroke={accent} strokeOpacity="0.35" strokeWidth="0.8" strokeDasharray="2 3" />
          <path d="M32 58 A26 26 0 0 1 6 32" fill="none" stroke={accent} strokeOpacity="0.35" strokeWidth="0.8" strokeDasharray="2 3" />
        </motion.g>
        {paths.map((d, i) => (
          <motion.path key={`${kind}${i}${active}`} d={d} fill="none" stroke="#eaf4ff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"
            initial={{ pathLength: 0, opacity: 0 }} animate={{ pathLength: 1, opacity: 1 }}
            transition={{ delay: 0.25 + i * 0.14, duration: 0.8, ease: 'easeOut' }} />
        ))}
      </svg>
    </motion.button>
  );
}
