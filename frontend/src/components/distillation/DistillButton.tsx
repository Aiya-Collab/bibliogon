import { useNavigate } from "react-router-dom";
export default function DistillButton({ bookId, count=0 }: { bookId:string; count?:number }) { const nav=useNavigate(); return <button onClick={()=>nav(`/distill/${bookId}`)}>蒸馏拆书 {count>0 && <small>({count})</small>}</button>; }
