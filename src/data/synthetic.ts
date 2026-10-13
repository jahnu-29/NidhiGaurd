export type RiskLevel = "High" | "Medium" | "Low";
export type Signal = "Cost Anomaly" | "Similar Project" | "Contractor Pattern" | "Billing Pattern" | "Geographic Pattern";
export type ProjectStatus = "Completed" | "In Progress" | "Sanctioned" | "Stalled";
export type QueueStatus = "Pending Review" | "Under Investigation" | "Reviewed" | "Closed";

export interface Project {
  id: string;
  description: string;
  type: string;
  constituency: string;
  district: string;
  contractor: string;
  sanctionedAmount: number;
  expenditure: number;
  status: ProjectStatus;
  startDate: string;
  completionDate: string;
  riskScore: number;
  riskLevel: RiskLevel;
  signals: Signal[];
  lat: number;
  lng: number;
  ward?: string;
}

export interface Contractor {
  name: string;
  totalProjects: number;
  totalValue: number;
  highRiskCount: number;
  avgProjectValue: number;
  riskIndicator: "Elevated" | "Moderate" | "Normal";
  state: string;
  registrationId: string;
}

export interface QueueItem {
  priority: number;
  projectId: string;
  riskScore: number;
  financialValue: number;
  signalCount: number;
  status: QueueStatus;
  assignedOfficer: string | null;
  addedDate: string;
}

export const CONSTITUENCIES = [
  "Constituency A", "Constituency B", "Constituency C",
  "Constituency D", "Constituency E", "Constituency F",
];

export const DISTRICTS = ["District North", "District South", "District East", "District West", "District Central"];

export const CONTRACTORS: Contractor[] = [
  { name: "ABC Infrastructure Pvt Ltd", totalProjects: 37, totalValue: 82000000, highRiskCount: 7, avgProjectValue: 221600, riskIndicator: "Elevated", state: "Maharashtra", registrationId: "REG-MH-04921" },
  { name: "XYZ Works & Constructions", totalProjects: 21, totalValue: 37000000, highRiskCount: 2, avgProjectValue: 176200, riskIndicator: "Normal", state: "Maharashtra", registrationId: "REG-MH-03714" },
  { name: "Bharat Nirman Ltd", totalProjects: 18, totalValue: 31500000, highRiskCount: 3, avgProjectValue: 175000, riskIndicator: "Moderate", state: "Maharashtra", registrationId: "REG-MH-05512" },
  { name: "Pioneer Civil Works", totalProjects: 14, totalValue: 22400000, highRiskCount: 0, avgProjectValue: 160000, riskIndicator: "Normal", state: "Maharashtra", registrationId: "REG-MH-02198" },
  { name: "Sagar Constructions", totalProjects: 12, totalValue: 19200000, highRiskCount: 4, avgProjectValue: 160000, riskIndicator: "Elevated", state: "Uttar Pradesh", registrationId: "REG-UP-11034" },
  { name: "National Builders Corp", totalProjects: 11, totalValue: 17600000, highRiskCount: 1, avgProjectValue: 160000, riskIndicator: "Normal", state: "Gujarat", registrationId: "REG-GJ-08821" },
  { name: "Greenfield Projects", totalProjects: 9, totalValue: 12600000, highRiskCount: 0, avgProjectValue: 140000, riskIndicator: "Normal", state: "Rajasthan", registrationId: "REG-RJ-06634" },
  { name: "Apex Infrastructure", totalProjects: 8, totalValue: 11200000, highRiskCount: 2, avgProjectValue: 140000, riskIndicator: "Moderate", state: "Karnataka", registrationId: "REG-KA-09102" },
  { name: "Sunrise Civil Contractors", totalProjects: 7, totalValue: 8400000, highRiskCount: 0, avgProjectValue: 120000, riskIndicator: "Normal", state: "Tamil Nadu", registrationId: "REG-TN-14522" },
  { name: "Prakash Engineering Works", totalProjects: 6, totalValue: 7200000, highRiskCount: 1, avgProjectValue: 120000, riskIndicator: "Normal", state: "Punjab", registrationId: "REG-PB-03211" },
  { name: "Metro Build Associates", totalProjects: 5, totalValue: 6000000, highRiskCount: 0, avgProjectValue: 120000, riskIndicator: "Normal", state: "Delhi", registrationId: "REG-DL-07811" },
  { name: "Ram Developers", totalProjects: 4, totalValue: 4400000, highRiskCount: 1, avgProjectValue: 110000, riskIndicator: "Moderate", state: "Bihar", registrationId: "REG-BR-01923" },
];

export const PROJECTS: Project[] = [
  { id: "P-1023", description: "Construction of Concrete Road – Ward 14", type: "Road", constituency: "Constituency A", district: "District North", contractor: "ABC Infrastructure Pvt Ltd", sanctionedAmount: 198000, expenditure: 198000, status: "Completed", startDate: "2025-03-12", completionDate: "2025-09-08", riskScore: 91, riskLevel: "High", signals: ["Cost Anomaly", "Similar Project", "Contractor Pattern", "Billing Pattern"], lat: 18.92, lng: 72.85, ward: "Ward 14" },
  { id: "P-0872", description: "Community Hall Renovation – Sector 7", type: "Community Building", constituency: "Constituency B", district: "District South", contractor: "XYZ Works & Constructions", sanctionedAmount: 164000, expenditure: 160000, status: "Completed", startDate: "2025-01-20", completionDate: "2025-07-14", riskScore: 84, riskLevel: "High", signals: ["Billing Pattern", "Contractor Pattern", "Cost Anomaly"], lat: 18.96, lng: 72.82, ward: "Sector 7" },
  { id: "P-1134", description: "Road Improvement Work – NH Link", type: "Road", constituency: "Constituency A", district: "District North", contractor: "ABC Infrastructure Pvt Ltd", sanctionedAmount: 178000, expenditure: 175000, status: "Completed", startDate: "2025-04-01", completionDate: "2025-10-15", riskScore: 79, riskLevel: "High", signals: ["Cost Anomaly", "Geographic Pattern", "Similar Project"], lat: 18.91, lng: 72.87, ward: "Ward 14" },
  { id: "P-1191", description: "Concrete Road Construction – Ward 16", type: "Road", constituency: "Constituency A", district: "District North", contractor: "ABC Infrastructure Pvt Ltd", sanctionedAmount: 192000, expenditure: 189000, status: "Completed", startDate: "2025-05-10", completionDate: "2026-01-18", riskScore: 76, riskLevel: "High", signals: ["Similar Project", "Geographic Pattern", "Contractor Pattern"], lat: 18.93, lng: 72.84, ward: "Ward 16" },
  { id: "P-0934", description: "Drainage System Upgrade – Zone B", type: "Drainage", constituency: "Constituency C", district: "District East", contractor: "Sagar Constructions", sanctionedAmount: 145000, expenditure: 142000, status: "Completed", startDate: "2025-02-14", completionDate: "2025-08-22", riskScore: 71, riskLevel: "High", signals: ["Billing Pattern", "Cost Anomaly"], lat: 19.04, lng: 72.91, ward: "Zone B" },
  { id: "P-1056", description: "Footpath Construction – Market Area", type: "Footpath", constituency: "Constituency D", district: "District West", contractor: "Bharat Nirman Ltd", sanctionedAmount: 98000, expenditure: 95000, status: "In Progress", startDate: "2025-08-01", completionDate: "2026-02-28", riskScore: 62, riskLevel: "Medium", signals: ["Cost Anomaly", "Contractor Pattern"], lat: 18.98, lng: 72.78, ward: "Market" },
  { id: "P-0789", description: "Street Light Installation – Phase 2", type: "Street Light", constituency: "Constituency B", district: "District South", contractor: "Apex Infrastructure", sanctionedAmount: 112000, expenditure: 108000, status: "Completed", startDate: "2024-11-05", completionDate: "2025-03-30", riskScore: 58, riskLevel: "Medium", signals: ["Billing Pattern", "Geographic Pattern"], lat: 18.94, lng: 72.83, ward: "Phase 2" },
  { id: "P-1302", description: "Drainage Repair – Old Town", type: "Drainage", constituency: "Constituency E", district: "District Central", contractor: "National Builders Corp", sanctionedAmount: 87000, expenditure: 84000, status: "Completed", startDate: "2025-06-01", completionDate: "2025-11-14", riskScore: 54, riskLevel: "Medium", signals: ["Cost Anomaly"], lat: 19.01, lng: 72.89, ward: "Old Town" },
  { id: "P-0654", description: "Park Development – Sector 12", type: "Parks & Gardens", constituency: "Constituency F", district: "District West", contractor: "Greenfield Projects", sanctionedAmount: 78000, expenditure: 74000, status: "In Progress", startDate: "2025-09-01", completionDate: "2026-03-15", riskScore: 41, riskLevel: "Medium", signals: ["Geographic Pattern"], lat: 19.07, lng: 72.76, ward: "Sector 12" },
  { id: "P-1400", description: "Boundary Wall Construction – School", type: "Education", constituency: "Constituency C", district: "District East", contractor: "Pioneer Civil Works", sanctionedAmount: 65000, expenditure: 63000, status: "Completed", startDate: "2025-03-25", completionDate: "2025-07-20", riskScore: 28, riskLevel: "Low", signals: [], lat: 19.05, lng: 72.92, ward: "Sector 5" },
  { id: "P-0512", description: "Drinking Water Supply – Village Extension", type: "Water Supply", constituency: "Constituency D", district: "District West", contractor: "Pioneer Civil Works", sanctionedAmount: 134000, expenditure: 130000, status: "Completed", startDate: "2024-10-01", completionDate: "2025-04-10", riskScore: 22, riskLevel: "Low", signals: [], lat: 18.97, lng: 72.77, ward: "Village Ext" },
  { id: "P-1244", description: "Primary Health Centre Renovation", type: "Healthcare", constituency: "Constituency E", district: "District Central", contractor: "Sunrise Civil Contractors", sanctionedAmount: 95000, expenditure: 92000, status: "Completed", startDate: "2025-01-10", completionDate: "2025-06-28", riskScore: 18, riskLevel: "Low", signals: [], lat: 19.00, lng: 72.88, ward: "Sector 3" },
  { id: "P-0321", description: "Road Widening – Sector 9 Approach", type: "Road", constituency: "Constituency F", district: "District West", contractor: "Sunrise Civil Contractors", sanctionedAmount: 107000, expenditure: 103000, status: "Completed", startDate: "2024-09-15", completionDate: "2025-02-14", riskScore: 15, riskLevel: "Low", signals: [], lat: 19.08, lng: 72.75, ward: "Sector 9" },
  { id: "P-1089", description: "Community Library Building", type: "Community Building", constituency: "Constituency B", district: "District South", contractor: "Metro Build Associates", sanctionedAmount: 156000, expenditure: 152000, status: "In Progress", startDate: "2025-07-01", completionDate: "2026-06-30", riskScore: 34, riskLevel: "Low", signals: [], lat: 18.95, lng: 72.81, ward: "Sector 7" },
  { id: "P-0443", description: "Sewerage Line Extension – Zone D", type: "Sewerage", constituency: "Constituency C", district: "District East", contractor: "Ram Developers", sanctionedAmount: 118000, expenditure: 115000, status: "Stalled", startDate: "2025-02-28", completionDate: "2025-08-31", riskScore: 55, riskLevel: "Medium", signals: ["Billing Pattern", "Cost Anomaly"], lat: 19.03, lng: 72.93, ward: "Zone D" },
];

export const QUEUE_ITEMS: QueueItem[] = [
  { priority: 1, projectId: "P-1023", riskScore: 91, financialValue: 198000, signalCount: 4, status: "Pending Review", assignedOfficer: null, addedDate: "2026-09-08" },
  { priority: 2, projectId: "P-0872", riskScore: 84, financialValue: 164000, signalCount: 3, status: "Pending Review", assignedOfficer: null, addedDate: "2026-09-08" },
  { priority: 3, projectId: "P-1134", riskScore: 79, financialValue: 178000, signalCount: 3, status: "Under Investigation", assignedOfficer: "Dy. Director K. Sharma", addedDate: "2026-09-06" },
  { priority: 4, projectId: "P-1191", riskScore: 76, financialValue: 192000, signalCount: 3, status: "Under Investigation", assignedOfficer: "Dy. Director K. Sharma", addedDate: "2026-09-06" },
  { priority: 5, projectId: "P-0934", riskScore: 71, financialValue: 145000, signalCount: 2, status: "Pending Review", assignedOfficer: null, addedDate: "2026-09-09" },
  { priority: 6, projectId: "P-1056", riskScore: 62, financialValue: 98000, signalCount: 2, status: "Reviewed", assignedOfficer: "Dir. M. Verma", addedDate: "2026-09-01" },
  { priority: 7, projectId: "P-0789", riskScore: 58, financialValue: 112000, signalCount: 2, status: "Reviewed", assignedOfficer: "Dir. M. Verma", addedDate: "2026-08-28" },
  { priority: 8, projectId: "P-0443", riskScore: 55, financialValue: 118000, signalCount: 2, status: "Pending Review", assignedOfficer: null, addedDate: "2026-09-10" },
];

export const SIGNAL_COLORS: Record<Signal, string> = {
  "Cost Anomaly": "#dc2626",
  "Similar Project": "#9333ea",
  "Contractor Pattern": "#d97706",
  "Billing Pattern": "#2563eb",
  "Geographic Pattern": "#0891b2",
};

export const SIGNAL_BG: Record<Signal, string> = {
  "Cost Anomaly": "#fef2f2",
  "Similar Project": "#faf5ff",
  "Contractor Pattern": "#fffbeb",
  "Billing Pattern": "#eff6ff",
  "Geographic Pattern": "#ecfeff",
};

export function formatINR(amount: number): string {
  if (amount >= 10000000) return `₹${(amount / 10000000).toFixed(1)} Cr`;
  if (amount >= 100000) return `₹${(amount / 100000).toFixed(1)}L`;
  return `₹${amount.toLocaleString("en-IN")}`;
}

export const KPI = {
  totalProjects: 1247,
  totalValue: 1864000000,
  highRisk: 43,
  anomalySignals: 217,
  investigationQueue: 61,
};
