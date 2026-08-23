import { useRef, useState } from "react";
import type { FormEvent } from "react";
import { ApiError } from "../api/client";
import * as copilotApi from "../api/copilot";
import * as imagesApi from "../api/images";
import type { Diagnosis, ImageAnalysis } from "../api/types";
import { DiagnosisView } from "../components/DiagnosisView";
import { ImageStatusBadge } from "../components/Badges";

interface SensorField {
  metric: string;
  value: string;
}

const DEFAULT_SENSOR_FIELDS: SensorField[] = [
  { metric: "temperature", value: "" },
  { metric: "vibration_rms", value: "" },
  { metric: "rpm", value: "" },
  { metric: "pressure", value: "" },
];

export function CopilotPage() {
  const [question, setQuestion] = useState("");
  const [equipmentId, setEquipmentId] = useState("");
  const [equipmentType, setEquipmentType] = useState("");
  const [sensorFields, setSensorFields] = useState<SensorField[]>(DEFAULT_SENSOR_FIELDS);

  const imageInputRef = useRef<HTMLInputElement>(null);
  const [imageAnalysis, setImageAnalysis] = useState<ImageAnalysis | null>(null);
  const [analyzingImage, setAnalyzingImage] = useState(false);
  const [imageError, setImageError] = useState<string | null>(null);

  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleAnalyzeImage() {
    const file = imageInputRef.current?.files?.[0];
    if (!file) return;
    setAnalyzingImage(true);
    setImageError(null);
    try {
      const result = await imagesApi.analyzeImage({
        file,
        equipmentType: equipmentType || undefined,
        equipmentId: equipmentId || undefined,
        question: question || undefined,
      });
      setImageAnalysis(result);
    } catch (err) {
      setImageError(err instanceof ApiError ? err.message : "Image analysis failed");
    } finally {
      setAnalyzingImage(false);
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!question.trim()) return;

    const sensorReadings: Record<string, number> = {};
    for (const field of sensorFields) {
      if (field.metric && field.value.trim() !== "") {
        const parsed = Number(field.value);
        if (!Number.isNaN(parsed)) sensorReadings[field.metric] = parsed;
      }
    }

    setSubmitting(true);
    setError(null);
    setDiagnosis(null);
    try {
      const result = await copilotApi.queryCopilot({
        question,
        equipmentId: equipmentId || undefined,
        equipmentType: equipmentType || undefined,
        imageAnalysisId:
          imageAnalysis && imageAnalysis.status === "ready" ? imageAnalysis.id : undefined,
        sensorReadings: Object.keys(sensorReadings).length > 0 ? sensorReadings : undefined,
      });
      setDiagnosis(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Diagnosis request failed");
    } finally {
      setSubmitting(false);
    }
  }

  function updateSensorField(index: number, value: string) {
    setSensorFields((prev) => prev.map((f, i) => (i === index ? { ...f, value } : f)));
  }

  return (
    <div className="stack" style={{ gap: 24 }}>
      <div>
        <h1>AI Copilot</h1>
        <p style={{ color: "var(--color-text-muted)", marginTop: 4 }}>
          Describe the issue. Add a photo and current sensor readings for a more grounded diagnosis.
        </p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: diagnosis ? "1fr" : "1fr", gap: 20 }}>
        <form onSubmit={handleSubmit} className="card card-pad stack" style={{ gap: 16 }}>
          {error && <div className="error-banner">{error}</div>}

          <div className="field">
            <label>Question</label>
            <textarea
              rows={3}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="The motor is making unusual noise. What could be wrong?"
              required
            />
          </div>

          <div style={{ display: "flex", gap: 12 }}>
            <div className="field" style={{ flex: 1 }}>
              <label>Equipment ID</label>
              <input
                value={equipmentId}
                onChange={(e) => setEquipmentId(e.target.value)}
                placeholder="MOTOR-001"
              />
            </div>
            <div className="field" style={{ flex: 1 }}>
              <label>Equipment type</label>
              <input
                value={equipmentType}
                onChange={(e) => setEquipmentType(e.target.value)}
                placeholder="electric_motor"
              />
            </div>
          </div>

          <div className="field">
            <label>Component photo (optional)</label>
            <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <input ref={imageInputRef} type="file" accept="image/jpeg,image/png,image/webp" />
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={handleAnalyzeImage}
                disabled={analyzingImage}
              >
                {analyzingImage ? "Analyzing…" : "Analyze image"}
              </button>
            </div>
            {imageError && <div className="error-banner" style={{ marginTop: 8 }}>{imageError}</div>}
            {imageAnalysis && (
              <div
                style={{
                  marginTop: 10,
                  padding: "10px 12px",
                  background: "var(--color-surface-alt)",
                  borderRadius: "var(--radius-sm)",
                  border: "1px solid var(--color-border)",
                }}
              >
                <ImageStatusBadge status={imageAnalysis.status} />
                {imageAnalysis.status === "ready" && (
                  <ul style={{ margin: "8px 0 0", paddingLeft: 18 }}>
                    {imageAnalysis.observations.map((obs, i) => (
                      <li key={i} style={{ fontSize: 13 }}>
                        {obs.description}{" "}
                        <span style={{ color: "var(--color-text-faint)" }}>
                          ({Math.round(obs.confidence * 100)}%)
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
                {imageAnalysis.status === "failed" && (
                  <p style={{ fontSize: 12, color: "var(--color-danger)", marginTop: 6 }}>
                    {imageAnalysis.error_message}
                  </p>
                )}
              </div>
            )}
          </div>

          <div className="field">
            <label>Current sensor readings (optional)</label>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10 }}>
              {sensorFields.map((field, i) => (
                <input
                  key={field.metric}
                  value={field.value}
                  onChange={(e) => updateSensorField(i, e.target.value)}
                  placeholder={field.metric}
                  inputMode="decimal"
                />
              ))}
            </div>
          </div>

          <button className="btn btn-primary" type="submit" disabled={submitting} style={{ alignSelf: "flex-start" }}>
            {submitting ? "Running diagnosis…" : "Run diagnosis"}
          </button>
        </form>

        {diagnosis && <DiagnosisView diagnosis={diagnosis} />}
      </div>
    </div>
  );
}
