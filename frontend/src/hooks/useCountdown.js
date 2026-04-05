import { useState, useEffect } from 'react'

export function useCountdown(targetDate) {
  const [timeLeft, setTimeLeft] = useState(calcTime(targetDate))

  function calcTime(target) {
    const diff = new Date(target) - new Date()
    if (diff <= 0) return { days: 0, hours: 0, minutes: 0, seconds: 0, expired: true }
    return {
      days:    Math.floor(diff / 86400000),
      hours:   Math.floor((diff % 86400000) / 3600000),
      minutes: Math.floor((diff % 3600000) / 60000),
      seconds: Math.floor((diff % 60000) / 1000),
      expired: false,
    }
  }

  useEffect(() => {
    const timer = setInterval(() => setTimeLeft(calcTime(targetDate)), 1000)
    return () => clearInterval(timer)
  }, [targetDate])

  return timeLeft
}