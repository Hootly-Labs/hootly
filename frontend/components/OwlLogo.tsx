export default function OwlLogo({ size = 36, className = "" }: { size?: number; className?: string }) {
  return (
    <img
      src="/logo.svg"
      alt="Hootly"
      style={{ display: "inline-block", height: size, width: "auto" }}
      className={`owl-logo ${className}`}
    />
  );
}
