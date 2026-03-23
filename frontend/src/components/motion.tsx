"use client"

import { motion, useMotionValue, useTransform, animate, useReducedMotion } from "framer-motion"
import { useEffect, useRef } from "react"

const springTransition = {
  type: "spring" as const,
  stiffness: 100,
  damping: 20,
}

const fadeUpVariants = {
  hidden: { opacity: 0, y: 20, filter: "blur(4px)" },
  visible: { opacity: 1, y: 0, filter: "blur(0px)" },
}

const staggerContainer = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.08,
      delayChildren: 0.1,
    },
  },
}

const staggerItem = {
  hidden: { opacity: 0, y: 16 },
  visible: {
    opacity: 1,
    y: 0,
    transition: springTransition,
  },
}

/**
 * FadeUp — 뷰포트 진입 시 부드러운 등장
 */
export function FadeUp({
  children,
  className,
  delay = 0,
}: {
  children: React.ReactNode
  className?: string
  delay?: number
}) {
  const shouldReduce = useReducedMotion()

  if (shouldReduce) {
    return <div className={className}>{children}</div>
  }

  return (
    <motion.div
      className={className}
      variants={fadeUpVariants}
      initial="hidden"
      whileInView="visible"
      viewport={{ once: true, margin: "-50px" }}
      transition={{ ...springTransition, delay }}
    >
      {children}
    </motion.div>
  )
}

/**
 * StaggerList — 자식 요소들 순차 등장
 */
export function StaggerList({
  children,
  className,
}: {
  children: React.ReactNode
  className?: string
}) {
  const shouldReduce = useReducedMotion()

  if (shouldReduce) {
    return <div className={className}>{children}</div>
  }

  return (
    <motion.div
      className={className}
      variants={staggerContainer}
      initial="hidden"
      whileInView="visible"
      viewport={{ once: true, margin: "-30px" }}
    >
      {children}
    </motion.div>
  )
}

export function StaggerItem({
  children,
  className,
}: {
  children: React.ReactNode
  className?: string
}) {
  const shouldReduce = useReducedMotion()

  if (shouldReduce) {
    return <div className={className}>{children}</div>
  }

  return (
    <motion.div className={className} variants={staggerItem}>
      {children}
    </motion.div>
  )
}

/**
 * CountUp — KPI 숫자 카운트업 애니메이션
 */
export function CountUp({
  value,
  formatter,
  className,
}: {
  value: number
  formatter: (n: number) => string
  className?: string
}) {
  const shouldReduce = useReducedMotion()
  const motionValue = useMotionValue(0)
  const rounded = useTransform(motionValue, (v) => formatter(v))
  const ref = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (shouldReduce) {
      if (ref.current) ref.current.textContent = formatter(value)
      return
    }

    const controls = animate(motionValue, value, {
      duration: 0.8,
      ease: [0.32, 0.72, 0, 1],
    })
    return controls.stop
  }, [value, motionValue, shouldReduce, formatter])

  if (shouldReduce) {
    return <span ref={ref} className={className}>{formatter(value)}</span>
  }

  return <motion.span ref={ref} className={className}>{rounded}</motion.span>
}

export { motion, staggerItem }
